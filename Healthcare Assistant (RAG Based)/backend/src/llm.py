from .config import GROQ_API_KEY,GROQ_MODEL
class GroqLLM:
    def __init__(self,api_key=None,model=None):
        self.api_key=api_key or GROQ_API_KEY; self.model=model or GROQ_MODEL; self.client=None
        if self.api_key:
            try:
                from groq import Groq
                self.client=Groq(api_key=self.api_key)
            except Exception: pass
    @property
    def available(self): return self.client is not None
    def chat(self,messages,temperature=.1,max_tokens=1000):
        if not self.client:return None
        r=self.client.chat.completions.create(model=self.model,messages=messages,temperature=temperature,max_tokens=max_tokens)
        return r.choices[0].message.content.strip()
