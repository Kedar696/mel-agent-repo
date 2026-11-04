# P4 standalone survey demo

A self-contained copy of the P4 survey writer with its own survey tab. It is separate from the team's
`mel/` package and `app/streamlit_app.py`, so nothing here affects the team's tests or CI
(`pytest` only reads `tests/`).

What it shows:
- the survey a farmer gets after chatting with FarmerChat, in Hindi or English (language button)
- the same survey as a mobile-app sheet, web chat, WhatsApp, Telegram and a voice call
- **what the agent remembers** about the farmer, and a "pretend this farmer's survey history" demo
  (history rules H1 to H4: repeat problem, known barrier, survey fatigue, light user)
- simulated answers, follow-up flags and the answer record

Run it (from this folder):

```
cd demo/p4_standalone
pip3 install pandas streamlit
streamlit run app/survey_tab.py
```

Then open http://localhost:8501. If Streamlit asks for an email, press Enter.

How many questions: direct-action advice gets 3 questions for medium or high severity and 2 for low;
every other advice type gets 2; light users and farmers who ignored recent surveys get fewer.
The questions are templates in `mel/writer/templates.py`, modelled on the golden set. Data is synthetic.
