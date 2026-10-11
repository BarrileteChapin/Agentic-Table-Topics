# Table Topics

**Local club.** Five seats. One speech. A sheet on the podium.

| Timer | Grammarian | Ah-Counter | Reviewer | Evaluator |
| :---: | :---: | :---: | :---: | :---: |
| <img src="app/media/timer/tm_img_cropped.jpg" alt="Timer" width="96"> | <img src="app/media/grammarian/tm_img_cropped.jpg" alt="Grammarian" width="96"> | <img src="app/media/ah-counter/tm_img_cropped.jpg" alt="Ah-Counter" width="96"> | <img src="app/media/reviewer/tm_img_cropped.jpg" alt="Reviewer" width="96"> | <img src="app/media/evaluator/tm_img_cropped.jpg" alt="Evaluator" width="96"> |

A browser club for Toastmasters table topics. Draw a topic, record a speech or paste one, and the five seats take their turn. Timer and Ah-Counter count on their own. Grammarian, Reviewer, and Evaluator each make one call to a model running on your machine through Microsoft Foundry Local. Whisper, the model, and the audio stay local.

> **The room.** A green hall, red seats, brass nameplates, and a wooden podium. Each portrait leans in while that seat is working, then the note appears under the nameplate. The evaluation sheet slides in from the side.

## How a round works

```mermaid
%%{init: {"theme": "base", "themeVariables": {"fontFamily": "Georgia, serif", "primaryTextColor": "#1c1914", "lineColor": "#6b4a28", "background": "#f7f1e4"}}}%%
flowchart TD
    UI["Browser<br/>topic, timer, record or paste"]
    API["FastAPI<br/>/api/session or /api/text"]
    STT["Speech-to-text<br/>Distil-Whisper"]
    State["Session state<br/>topic, speech, times, pace"]
    Club["Sequential club"]
    Timer["Timer<br/>no model"]
    Gram["Grammarian<br/>one model call"]
    Ah["Ah-Counter<br/>no model"]
    Rev["Reviewer<br/>one model call"]
    Eval["Evaluator<br/>one model call"]
    Foundry["Foundry Local model"]
    Screen["Seats on screen<br/>SSE events"]

    UI -->|audio| API
    UI -->|pasted text| API
    API --> STT
    STT --> State
    API -->|typed speech, pace from word count| State
    State --> Club
    Club --> Timer --> Gram --> Ah --> Rev --> Eval
    Gram --> Foundry
    Rev --> Foundry
    Eval --> Foundry
    Timer -->|timing note| State
    Gram -->|wording note| State
    Ah -->|filler note| State
    Rev -->|topic, clarity, organization| State
    State -->|those notes plus pace| Eval
    Eval --> Screen
    Timer --> Screen
    Gram --> Screen
    Ah --> Screen
    Rev --> Screen

    classDef paper fill:#f7f1e4,stroke:#1c1914,stroke-width:2px,color:#1c1914
    classDef seat fill:#8d2d32,stroke:#1c1914,stroke-width:2px,color:#f6f1e7
    classDef brass fill:#e6c14a,stroke:#1c1914,stroke-width:2px,color:#1c1914
    classDef green fill:#1f3d32,stroke:#e6c14a,stroke-width:2px,color:#f3e6c4

    class UI,API,STT,State paper
    class Timer,Ah,Screen brass
    class Gram,Rev,Eval seat
    class Foundry,Club green
```

You send a speech. A recording is transcribed first. Pasted text skips Whisper, and pace is a word count. Both paths land in one session: topic, target time, elapsed time, transcript, a shortened speech, and a pace note.

The club then runs the seats in order. Each one writes its note back into that session. The browser hears them as server-sent events and paints the seat as soon as it reports.

Grammarian reads the speech. Reviewer reads the topic and the speech. The Evaluator is the seat that combines the timer, the wording, the fillers, the review, and the pace into the eight-line sheet.

| Seat | Model | Reads | Writes |
| --- | --- | --- | --- |
| Timer | No | Elapsed time against the target | Short, green, yellow, or over |
| Grammarian | Yes | The speech | What wording worked, and what to change |
| Ah-Counter | No | The full transcript | Filler counts: um, uh, ah, er, hmm, you know |
| Reviewer | Yes | Topic and speech | Topic fit, clarity, organization |
| Evaluator | Yes | The four notes plus pace | Clarity, vocal variety, audience awareness, comfort, content, excelled at, work on, challenge |

Long speeches are trimmed to an opening, a middle, and a close before they reach the model. The Ah-Counter still counts fillers on the full transcript.

## What you need

- **Python 3.10+**
- The packages in `requirements.txt`: Google ADK, LiteLLM, FastAPI, Uvicorn, and faster-whisper
- **[Foundry Local](https://learn.microsoft.com/en-us/azure/ai-foundry/foundry-local/)** on your PATH, with the service running and a chat model loaded
- A browser. The microphone is only needed when you press Record
- On the first recording, Distil-Whisper Small English downloads unless `models/distil-small.en` is already present. Transcription runs on CPU

The default model is `qwen2.5-1.5b-instruct-generic-gpu:4`. The menu lists whatever Foundry is serving, and the round uses the one you pick.

## Run the club

From the project folder:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
foundry service start
uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

| Variable | What it does |
| --- | --- |
| `FOUNDRY_MODEL` | Model id used when the page does not send one |
| `FOUNDRY_API_BASE` | Foundry’s OpenAI-compatible base URL, if `foundry service status` cannot be read |
