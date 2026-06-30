# 🚀 PrepAI

<p align="center">
  <img src="assets/demo.gif" alt="PrepAI Demo" width="100%">
</p>

<p align="center">
  <h3 align="center">🧠 Your Personal AI Operating System for Interview Success</h3>
</p>

<p align="center">
  Resume → Memory → Planning → Practice → Interviews → Offer Letter
</p>

<p align="center">

![Python](https://img.shields.io/badge/Python-3.11+-blue?style=for-the-badge\&logo=python)
![Tauri](https://img.shields.io/badge/Tauri-Desktop_App-orange?style=for-the-badge\&logo=tauri)
![Flask](https://img.shields.io/badge/Flask-Backend-black?style=for-the-badge\&logo=flask)
![Claude](https://img.shields.io/badge/Claude-AI-teal?style=for-the-badge)
![Gemini](https://img.shields.io/badge/Gemini-AI-blue?style=for-the-badge)
![Groq](https://img.shields.io/badge/Groq-Ultra_Fast-orange?style=for-the-badge)

</p>

<p align="center">

<a href="#-why-prepai">Why PrepAI?</a> • <a href="#-features">Features</a> • <a href="#-choose-your-journey">Choose Your Journey</a> • <a href="#-architecture">Architecture</a> • <a href="#-installation">Installation</a> • <a href="#-roadmap">Roadmap</a>

</p>

---

# 🎯 Why PrepAI?

Most interview platforms stop at giving you questions.

**PrepAI goes further.**

It remembers your strengths, identifies your weaknesses, plans your preparation, generates verified interview questions, tracks progress, and adapts as you improve.

> **PrepAI doesn't just answer questions.**
>
> It remembers.
>
> It plans.
>
> It coaches.
>
> It evolves with you.

---

# ⚡ Features

<table>
<tr>
<td width="50%">

## 🧠 Persistent Memory

PrepAI continuously learns from:

* Resume uploads
* Practice sessions
* Weak areas
* Coding history
* Progress over time

The more you use PrepAI, the smarter it becomes.

</td>

<td width="50%">

## 🤖 Autonomous Agent

Set a goal such as:

> *"Get me ready for a Google SWE interview in 14 days."*

PrepAI automatically:

* Plans
* Prioritizes
* Searches
* Recommends
* Tracks progress

</td>
</tr>

<tr>
<td>

## 📄 Resume Intelligence

Upload your resume and PrepAI extracts:

* Skills
* Projects
* Experience
* Weaknesses
* Career focus

</td>

<td>

## 🧪 AI Question Judge

Questions are not blindly accepted.

Each question is:

```text
Generate
    ↓
Judge
    ↓
Validate
    ↓
Store
```

Cross-model validation reduces hallucinations.

</td>
</tr>

<tr>
<td>

## 📅 Adaptive Preparation Timeline

Generate personalized roadmaps based on:

* Interview date
* Role
* Current skill level
* Experience

</td>

<td>

## 🔍 AI Job Scanner

Discover relevant opportunities using:

* Google Search Grounding
* Skill matching
* Resume-aware recommendations

</td>
</tr>

<tr>
<td>

## 💻 Coding Practice Assistant

Integrated support for:

* LeetCode tracking
* Weak topic detection
* Daily coding queues

</td>

<td>

## 🔔 Smart Notifications

Never miss:

* Daily preparation reminders
* Interview countdowns
* Job deadlines
* Coding sessions

</td>
</tr>

</table>

---

# 🎬 Demo

<p align="center">
  <img src="ui\static\mockup.png" width="90%">
</p>

---

# 🎯 Choose Your Journey

## 📄 I already have a Resume

<details>
<summary><b>Click to expand</b></summary>

```text
Upload Resume
        ↓
Skill Extraction
        ↓
Weakness Detection
        ↓
Preparation Timeline
        ↓
Question Practice
        ↓
Interview Ready 🚀
```

</details>

---

## 💼 I'm actively applying for jobs

<details>
<summary><b>Click to expand</b></summary>

```text
Scan Jobs
      ↓
Match Skills
      ↓
Generate Projects
      ↓
Fill Skill Gaps
      ↓
Track Applications
      ↓
Land Interviews 🚀
```

</details>

---

## 🎯 I have an interview soon

<details>
<summary><b>Click to expand</b></summary>

```text
Set Interview Date
          ↓
Generate Timeline
          ↓
Practice Questions
          ↓
Mock Preparation
          ↓
Daily Focus
          ↓
Crack the Interview 🚀
```

</details>

---

## 🤖 I want PrepAI to do everything

<details>
<summary><b>Click to expand</b></summary>

```text
Set Goal
    ↓
Agent Plans
    ↓
Agent Executes
    ↓
Daily Coaching
    ↓
Progress Tracking
    ↓
Continuous Improvement 🚀
```

</details>

---

# 🏗️ Architecture

```text
                        ┌────────────────────┐
                        │       User         │
                        └─────────┬──────────┘
                                  │
                                  ▼
                   ┌─────────────────────────┐
                   │      PrepAI Desktop     │
                   │     (Tauri + HTML)      │
                   └─────────┬───────────────┘
                             │
                             ▼
                  ┌──────────────────────────┐
                  │      Flask Backend       │
                  └─────────┬────────────────┘
                            │
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼

   Claude AI          Gemini AI          Groq AI

         └──────────────────┼──────────────────┘
                            ▼

                  ┌──────────────────────────┐
                  │   Persistent Memory DB   │
                  └──────────────────────────┘
```

---

# 🛠️ Tech Stack

| Layer         | Technologies          |
| ------------- | --------------------- |
| Desktop       | Tauri                 |
| Backend       | Flask                 |
| Frontend      | HTML, CSS, JavaScript |
| AI Models     | Claude, Gemini, Groq  |
| Database      | SQLite                |
| Notifications | OneSignal             |
| Packaging     | GitHub Actions + MSI  |

---

# 🚀 Installation

## Clone the repository

```bash
git clone https://github.com/yourusername/prepai.git
cd prepai
```

## Create environment

```bash
python -m venv venv
```

### Windows

```bash
venv\Scripts\activate
```

### Linux / macOS

```bash
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Install frontend dependencies:

```bash
npm install
```

Run:

```bash
python app.py
```

Desktop development:

```bash
npm run tauri dev
```

Build MSI:

```bash
npm run tauri build
```

---

# 🧠 AI Engine Strategy

PrepAI intelligently routes requests across multiple providers.

```text
Claude → Deep reasoning
Gemini → Search grounding
Groq → Ultra-fast inference
```

Auto Mode:

```text
Claude
   ↓
Fallback to Gemini
   ↓
Fallback to Groq
```

---

# 🗺️ Roadmap

* [x] Resume Intelligence
* [x] Persistent Memory
* [x] AI Question Judge
* [x] Adaptive Timelines
* [x] Autonomous Agent
* [x] Desktop Packaging
* [x] Notification Engine
* [ ] Voice Mock Interviews
* [ ] Local LLM Support
* [ ] Multi-Agent Collaboration
* [ ] Browser Extension
* [ ] Interview Copilot Mode

---

# 🤝 Contributing

Contributions are welcome.

Feel free to:

* Open issues
* Submit pull requests
* Suggest features
* Report bugs

---

# ⭐ Support

If you find PrepAI useful, consider giving this repository a star.

It helps the project grow and motivates further development.

<p align="center">

⭐ **Star the repository if PrepAI helped you prepare better.** ⭐

</p>

---

<p align="center">
Made with ❤️ for every candidate chasing their dream job.
</p>
