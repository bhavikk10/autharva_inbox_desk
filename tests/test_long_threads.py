from backend.fixtures import seed_threads


def test_long_threads_are_real_conversations_with_readable_mail_lengths():
    threads=[t for t in seed_threads() if t['id'].startswith('long-')]
    assert len(threads)==28
    for thread in threads:
        assert 5<=len(thread['messages'])<=7
        assert {'inbound','outbound'}<=set(m['direction'] for m in thread['messages'])
        for message in thread['messages']:
            assert 30<=len(message['body'].split())<=40,(thread['id'],message['id'],len(message['body'].split()))
