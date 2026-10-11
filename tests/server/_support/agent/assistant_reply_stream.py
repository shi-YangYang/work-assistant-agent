"""Shared controlled fixtures extracted from test_assistant_reply_stream."""



class CapturingPublisher:
    def __init__(self):
        self.values = []
    async def write(self, text, **options):
        self.values.append(text)
    async def withdraw(self):
        self.values.append(None)
