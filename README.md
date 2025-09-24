# ransomeware.agent

## Introduction

**ransomeware.agent** is my ([kk4w4i](https://github.com/kk4w4i)) thesis project focused on intelligent monitoring of public name-and-shame ransomware sites hosted on the TOR network. 

The aim is to support forensics and investigators by automating the monitoring process against to volatile dark web resources.

Inspired by existing efforts like [ransomware.live](https://ransomware.live) and frameworks like Agent-E by emergence.ai, this project explores agentic workflows for ransomware site analysis.

> If you’re interested in technical details, see my [thesis paper](#) (TBA).  
> For professional contact or questions, connect on [LinkedIn](https://www.linkedin.com/in/kintarokawai/).

***

## What is This Repo?

This repository contains the **source code for the ransomware.agent API**.  
It is **not a standalone end-user application**—it is the backend logic and services powering the ransomware.agent system.

- Access to a configured database (and environment-specific infrastructure) is required.
- Running this code independently will not provide meaningful functionality due to secure database and dependency requirements.
- Usage is restricted to authorized services, researchers, and contributors.

***

## Setup (Developers/Contributors Only)

**Requirements**
- Python 3.10+
- Docker (for integration testing, optional)
- Access to the configured database (credentials required)

**Quick Start for Development/Testing:**

1. **Clone the repo:**
   ```bash
   git clone https://github.com/kk4w4i/ransomeware.agent.git
   cd ransomeware.agent
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment:**
   - Update your `.env` file or `config.yaml` with *valid* database connection strings and any API keys.
   - Database credentials and access are **not** included in this repository for security.

4. **Run API server (for dev):**
   ```bash
   python app.py
   ```

**Note:**
- The agent will not operate without valid database and infrastructure connections.
- This codebase serves primarily as a backend microservice/API component.

***

## Contributions & Inquiries

- Feel free to submit issues or PRs for improvements and bug fixes.
- For research or collaboration discussions, reach out through [LinkedIn](https://www.linkedin.com/in/kintarokawai/).


