# KYA-Trust

Team Versae (Kartik Acharya, Prachi Kumawat) · Perfios x Techfest IIT Bombay, Theme 2, Problem 2: Know Your Agent.

For each banking session, KYA-Trust says who is acting (human, scripted bot or LLM agent), gives an
explainable Agent Trust Score (0–100), and recommends allow, step-up, hold or block before money moves.

## Setup

Both machines use Python 3.13 and Node.js 22 LTS.

Windows (PowerShell):

    py -3.13 -m venv .venv
    .venv\Scripts\Activate.ps1
    pip install -r requirements.txt

Mac:

    python3.13 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

Frontend (`bank/frontend`): Node.js 22 LTS, then `npm install` and `npm run dev`.

The rest of this README (running the demo, reproducing every number) is filled in by 10 Dec.
