"""Resolve supported raw phrases against the source message, never model-computed dates."""
import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TZ = ZoneInfo('Asia/Kolkata')
WEEKDAYS = ['monday','tuesday','wednesday','thursday','friday','saturday','sunday']
MONTHS = {name.lower(): i for i,name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): i for i,name in enumerate(calendar.month_abbr) if name})


@dataclass
class ResolvedDate:
    due_at: datetime | None
    note: str | None = None
    attention_start: datetime | None = None
    day_end: datetime | None = None


OFFSETS={'ist':330,'utc':0,'gmt':0,'pst':-480,'pdt':-420,'est':-300,'edt':-240,
         'mst':-420,'mdt':-360,'cet':60,'cest':120}


def resolve_date(expression: str, source_time: datetime, *, purpose='due_by', default_timezone='Asia/Kolkata', source_zone=None) -> ResolvedDate:
    if purpose not in ['due_by','not_before']: raise ValueError('Unknown date purpose.')
    raw = expression.strip().lower().replace(chr(8217), "'")
    if re.search(r'\b(?:after|before)\b.*\b(?:meeting|demo|approval|review|call)\b',raw):
        return ResolvedDate(None,f'Conditional date: "{expression}". Confirm the event and timing first.')
    if re.search(r'\b(?:cst|cdt|bst|ast)\b',raw):
        return ResolvedDate(None,f'Ambiguous timezone in "{expression}". Specify an offset or IANA zone.')
    display_zone=ZoneInfo(default_timezone)
    zone=source_zone or display_zone
    zone_offset=re.search(r'\b(?:utc|gmt)\s*([+-])(\d{1,2})(?::?(\d{2}))?\b',raw)
    named_zone=re.search(r'\b[A-Za-z_]+/[A-Za-z_]+(?:/[A-Za-z_]+)?\b',expression)
    if zone_offset:
        hours,minutes=int(zone_offset[2]),int(zone_offset[3] or 0)
        if hours>14 or minutes>59 or (hours==14 and minutes):
            return ResolvedDate(None,'Invalid explicit timezone offset.')
        zone=timezone(timedelta(minutes=(hours*60+minutes)*(1 if zone_offset[1]=='+' else -1)))
    elif named_zone:
        try: zone=ZoneInfo(named_zone[0])
        except ZoneInfoNotFoundError: return ResolvedDate(None,'Unknown IANA timezone; clarify the date.')
    else:
        for abbreviation,minutes in OFFSETS.items():
            if re.search(r'\b'+abbreviation+r'\b',raw):
                zone=timezone(timedelta(minutes=minutes));break
    base=source_time.astimezone(zone)
    day = None
    default_hour=9 if purpose=='not_before' else 17
    note=f'No time specified; {purpose} uses {default_hour:02d}:00 in {zone}. Explicit email zones override source metadata and the selected fallback zone.'
    try:
        iso = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', raw)
        named = re.search(r'\b(' + '|'.join(MONTHS) + r')\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b', raw)
        numeric = re.search(r'\b(\d{1,2})\s+(' + '|'.join(MONTHS) + r')(?:\s+(\d{4}))?\b', raw)
        if iso: day = datetime.strptime(iso[1], '%Y-%m-%d').date()
        elif named:
            day = datetime(int(named[3] or base.year), MONTHS[named[1]], int(named[2])).date()
        elif numeric:
            day = datetime(int(numeric[3] or base.year), MONTHS[numeric[2]], int(numeric[1])).date()
        elif 'tomorrow' in raw: day = (base + timedelta(days=1)).date()
        elif any(w in raw for w in ['today','tonight','this afternoon','end of day','eod']): day = base.date()
        elif 'end of month' in raw or 'month-end' in raw:
            day = base.replace(day=calendar.monthrange(base.year,base.month)[1]).date()
        elif 'next week' in raw:
            day = (base + timedelta(days=7-base.weekday())).date()
            note = f'Next week means Monday of the next calendar week, {default_hour:02d}:00 in the stated zone.'
        elif 'in a week' in raw or 'in one week' in raw:
            day = (base + timedelta(days=7)).date()
        else:
            day_offset = re.search(r'\bin (\d+) days?\b', raw)
            if day_offset: day = (base + timedelta(days=int(day_offset[1]))).date()
            else:
                for idx, weekday in enumerate(WEEKDAYS):
                    if re.search(r'\b' + weekday + r'\b', raw):
                        delta = (idx - base.weekday()) % 7
                        if 'next ' in raw and delta == 0: delta = 7
                        day = (base + timedelta(days=delta)).date()
                        break
        if day is None:
            return ResolvedDate(None, f'Unresolved date: "{expression}". Needs clarification.')
        hour, minute = default_hour, 0
        clock_raw=raw[:zone_offset.start()]+' '+raw[zone_offset.end():] if zone_offset else raw
        explicit_time = re.search(r'\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b', clock_raw)
        clock = re.search(r'\b(?:at\s+)?(\d{1,2}):(\d{2})\b', clock_raw)
        if explicit_time:
            if not 1<=int(explicit_time[1])<=12: raise ValueError('Invalid 12-hour clock')
            hour,minute = int(explicit_time[1]) % 12, int(explicit_time[2] or 0)
            if explicit_time[3] == 'pm': hour += 12
            note = None
        elif clock:
            hour,minute = int(clock[1]),int(clock[2]); note = None
        naive=datetime(day.year,day.month,day.day,hour,minute)
        local=naive.replace(tzinfo=zone)
        if isinstance(zone,ZoneInfo) and local.utcoffset()!=naive.replace(tzinfo=zone,fold=1).utcoffset():
            return ResolvedDate(None,f'Ambiguous or nonexistent daylight-saving time in "{expression}". Clarify the offset.')
        start=datetime(day.year,day.month,day.day,9,tzinfo=zone)
        end=datetime(day.year,day.month,day.day,tzinfo=zone)+timedelta(days=1)
        return ResolvedDate(local.astimezone(display_zone),note,start.astimezone(display_zone),end.astimezone(display_zone))
    except (ValueError, OverflowError):
        return ResolvedDate(None, f'Invalid or ambiguous date: "{expression}". Needs clarification.')
