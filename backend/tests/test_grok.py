import asyncio
import sys
print("Script started")  # add this

from services.transcription import transcribe_audio

class FakeFile:
    def __init__(self, path):
        with open(path, "rb") as f:
            self.content = f.read()
        self.filename = "test.wav"
        self.content_type = "audio/wav"
    
    async def read(self):
        return self.content

async def main():
    print("Creating fake file...")  # add this
    fake = FakeFile("test_audio.wav")
    print("Calling transcribe_audio...")  # add this
    result = await transcribe_audio(fake)
    print(result)

asyncio.run(main())