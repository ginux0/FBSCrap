# ◈ FBSCRAP v2.0
### Social Media Threat Intelligence Platform

**FBSCRAP** is a forensic-grade intelligence platform for detecting, documenting, and neutralizing coordinated inauthentic behavior (CIB) on Facebook. Purpose-built for political campaigns, governments, and organizations facing organized disinformation attacks.

---

## 🎯 What It Does

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

## 💻 Usage

### Scan for Coordinated Behavior
```bash
python3 fbscrap.py scan --page "target_page_name" --comments-on-top 100
```

### Continuous Monitoring (24/7)
```bash
python3 fbscrap.py monitor --page "page_name" --monitor-interval 300
```

### Generate Judicial Report
```bash
python3 fbscrap.py report --session-dir ./sessions/scan_date --format docx
```

---

## 📊 CIB Score (0–100)

- **0–30**: Organic activity
- **30–60**: Suspicious patterns
- **60–80**: Coordinated behavior detected
- **80–100**: Confirmed coordinated inauthentic behavior

---

## 🔍 Forensic Engines

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

## 📄 License

Proprietary. Contact author for licensing.

---

## 👤 Author

**Jesus Lugo** — Offensive Security Research  
Email: gin@linux.edu

---

*"Forensic precision against coordinated deception."*
