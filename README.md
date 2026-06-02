# FBSCRAP v2.0
### Social Media Threat Intelligence Platform

**FBSCRAP** is a forensic-grade intelligence platform for detecting, documenting, and neutralizing coordinated inauthentic behavior (CIB) on Facebook. Purpose-built for political campaigns, governments, and organizations facing organized disinformation attacks.

---

## What It Does

FBSCRAP detects coordinated bot campaigns with **forensic precision**:

- **Coordinated Inauthentic Behavior Detection** — Identifies synchronized attacks across multiple accounts with mathematical proof
- **Bot Classification** — 36 forensic engines analyzing 11 dimensions of bot risk
- **Narrative Mutation Tracking** — Detects when attack messaging changes while maintaining operational control
- **Temporal Analysis** — Proves coordination through timing synchronization (1–3 second attack waves)
- **Judicial Evidence Export** — Generates SHA-256 hashed, chain-of-custody reports ready for courts and prosecutors

---

## 🚀 Installation

```bash
git clone https://github.com/yourusername/fbscrap.git
cd fbscrap
pip install -r requirements.txt
cp config/default_config.json config.json
```

---

## 💻 Syntax & How to use

### First Time: Save Facebook Session
```bash
python3 fbscrap.py login
```
Opens browser for manual login (saves persistent session for automation).

### Scrape Pages for CIB Detection
```bash
python3 fbscrap.py page --targets targets/example_pages.json --days 7 --sentiment
```
Analyzes posts and comments from target pages for coordinated inauthentic behavior.

### Search Facebook + Sentiment Analysis
```bash
python3 fbscrap.py search --query "target name" --days 7 --sentiment
```
Search Facebook posts matching keyword(s) and analyze sentiment patterns.

### Deep Scrape Specific Posts (Forensic Collection)
```bash
python3 fbscrap.py comments --url "https://www.facebook.com/.../posts/..." --max-comments 500
```
Extract all comments on specific posts with full forensic metadata.

### Multi-Source Campaign Analysis
```bash
python3 fbscrap.py full --query "target name" --targets targets/example_pages.json --days 7 --top 30
```
Run comprehensive analysis: page scraping + search + sentiment + CIB scoring + HTML report.

### Continuous 24/7 Monitoring with Alerts
```bash
python3 fbscrap.py monitor --query "target name" --monitor-interval 300
```
Real-time monitoring with Telegram alerts on CIB score spikes and new bot detection.

### Compare Sessions for Campaign Evolution
```bash
python3 fbscrap.py delta --delta-before sessions/target/20260101/ --delta-after sessions/target/20260108/
```
Detect how attack narratives mutate, new bots appear, and campaigns escalate over time.

### Generate Report from Existing Data
```bash
python3 fbscrap.py report --data sessions/target_name/20260101_120000/posts_latest.json --top 30
```
Re-generate reports and forensic analysis without needing to re-scrape.

### List All Sessions
```bash
python3 fbscrap.py sessions
```
Show all recorded scan sessions and their metadata.

---

## 📊 CIB Score (0–100)

- **0–30**: Organic activity
- **30–60**: Suspicious patterns
- **60–80**: Coordinated behavior detected
- **80–100**: Confirmed coordinated inauthentic behavior

---

## Forensic Engines

11-dimensional analysis covering:
- Bot profile classification (TrollHunter)
- Network coordination (CIB Graph)
- Temporal synchronization (Temporal Waves)
- Inorganic amplification (Dark Amplification)
- Narrative mutations and vocabulary changes
- Cross-page persistence
- Comment cascade timing
- Multi-source coordination

---

## License

Proprietary. Contact author for licensing.

---

## 👤 Author

**Jesus Lugo** — Offensive Security Research  
Email: jesus@linux.edu
NULLSEC RED TEAM

---

*"Forensic precision against coordinated deception."*
