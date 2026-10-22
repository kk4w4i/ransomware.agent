# ransomware.agent

## Introduction

**ransomware.agent** is my ([kk4w4i](https://github.com/kk4w4i)) thesis project focused on intelligent monitoring of ransomware Data Leak Sites (DLS) hosted on the TOR network. 

The aim is to support forensics and investigators by improving the robustness of the automated monitoring process against the volatile nature of the DLS extortion pages.

Inspired by existing efforts like [ransomware.live](https://ransomware.live) and AI agentic frameworks like Agent-E by emergence.ai, this project explores agentic web navigation workflows for DLS analysis.

> For contact or questions, let's connect on [LinkedIn](https://www.linkedin.com/in/kintarokawai/).

***

## How does it work?

![UQ-Thesis-Poster](https://github.com/user-attachments/assets/b49c256d-53bb-47e8-ad84-452121dfa932)

### Quick Demonstration

[![Watch the demo](https://img.youtube.com/vi/P3jPkyzt8G0/hqdefault.jpg)](https://youtu.be/P3jPkyzt8G0)

## Results

The agent was benchmarked against [ransomware.live](https://ransomware.live)'s hand-written parsers on five ransomware groups: Akira, DragonForce, Qilin, Play and The Gentlemen. Field accuracy is the cosine similarity between `all-MiniLM-L6-v2` sentence embeddings of the agent's output and ransomware.live's data.

- **Victim names:** 84-100% semantic similarity across all five groups.
- **Coverage:** 100% on The Gentlemen (43 victims) and 95.6% on Qilin's 33-page, 457-victim table; lowest was 41.7% on Akira's terminal-style interface.
- **Known limitations:** pages listing more than ~20-25 victims exceed the model's output token budget, and long scrapes cannot yet detect or recover from dropped Tor connections.

## So what does this Repo contain?

This repository contains the **source code for the ransomware.agent API**.  
It is **not a standalone end-user application**—it is the backend logic and services powering the ransomware.agent system.

- Access to a configured database (MongoDB uri) is required.
- Running this code independently will not provide meaningful functionality due to database and other dependency requirements.
