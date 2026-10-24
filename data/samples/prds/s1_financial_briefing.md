# BriefCast: AI briefings from financial reports

Sample product document S1 for testing the council. Fictional company, written for this project.

<!-- page: 1 -->
## 1. Purpose

Kestrel Holdings publishes annual reports and quarterly results as long PDF documents.
Analysts and the investor relations team spend days turning them into short briefings.

BriefCast turns a financial document into an AI-generated summary, a narration script, an audio
briefing and an avatar video. Users can regenerate any summary or script before approving it.

Every briefing must be approved by a person before it is shared, because figures in a financial
summary must match the source document exactly.

<!-- page: 2 -->
## 2. Users and team

BriefCast is an internal tool used by about 150 analysts and investor relations staff each day.
All users are based in India.
Users sign in with their company accounts, and the system stores each user's name and email.

The engineering team has five developers and one designer.
Kestrel Holdings already runs its applications on Azure.

<!-- page: 3 -->
## 3. Features

- Upload a PDF annual report or quarterly results document of up to 300 pages.
- Generate a summary of the key figures, risks and outlook, with a page reference for every figure.
- Generate a narration script from the approved summary, then audio and an avatar video.
- Video rendering can take several minutes, so jobs run in the background and users are notified when they finish.
- Keep a history of every version and who approved it.

<!-- page: 4 -->
## 4. Constraints

- The monthly cloud budget for the pilot is ₹2,00,000.
- Documents and briefings must stay in India.
- Services are packaged as containers and deployed through GitHub Actions.
- The pilot should be live within three months.
- The tool is not exposed to the public internet; it is available only on the company network.
