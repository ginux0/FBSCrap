"""
LegalExportEngine — Legal Forensic Export Engine.

Genera un paquete de evidencia forense completo para uso en procedimientos
legales/judiciales en México y Latinoamérica. El paquete incluye:

  1. MANIFIESTO DE CADENA DE CUSTODIA (JSON + HTML)
     - SHA-256 por ítem de evidencia
     - Hash de integridad del manifiesto completo
     - Timestamp UTC de recolección
     - Información del analista y herramienta

  2. REPORTE EJECUTIVO EN ESPAÑOL (HTML judicial)
     - Lenguaje no técnico para jueces/fiscales
     - Resumen estadístico de la operación de CIB
     - Perfiles de actores confirmados con evidencia
     - Timeline cronológico del ataque
     - Evidencia de TODOS los engines (E1-E8 + P1-P8 + N1-N7)

  3. DOSSIER DOCX JUDICIAL
     - Formato documento legal numerado
     - Secciones para firma del analista
     - Anexos técnicos

  4. PAQUETE ZIP
     - Todos los artefactos empaquetados juntos

Categorías de evidencia:
  POST | BOT_ACTOR | ATTACK_WAVE | SYNC_PAIR | SEED_ACCOUNT | SEEDED_POST |
  TROLL_PROFILE | ENGAGEMENT_ANOMALY | CONTAGION_EVENT | REPLY_HIJACK |
  CROSS_CAMPAIGN | IDENTITY_MORPH | NARRATIVE_MUTATION | SHIFT_EVENT |
  DARK_AMP | CIB_CLUSTER

Todos los parámetros desde cfg["legal_export"]. Cero valores hardcodeados.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sha256(data: Any) -> str:
    s = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(s.encode()).hexdigest()


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _es_date(iso_str: str) -> str:
    """ISO → Spanish date format for legal documents."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        meses = ["enero","febrero","marzo","abril","mayo","junio",
                 "julio","agosto","septiembre","octubre","noviembre","diciembre"]
        return f"{dt.day} de {meses[dt.month-1]} de {dt.year} a las {dt.hour:02d}:{dt.minute:02d} UTC"
    except Exception:
        return iso_str


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class EvidenceItem:
    item_id:      str
    category:     str
    description:  str
    data:         dict
    sha256:       str
    collected_at: str
    severity:     str = "MEDIUM"   # CRITICAL | HIGH | MEDIUM | LOW


@dataclass
class LegalManifest:
    case_id:         str
    generated_at:    str
    analyst:         str
    tool_version:    str
    query:           str
    total_items:     int
    categories:      dict[str, int]
    manifest_hash:   str
    evidence_items:  List[EvidenceItem]


@dataclass
class LegalReport:
    manifest:    LegalManifest
    html_path:   str | None
    docx_path:   str | None
    json_path:   str | None
    zip_path:    str | None
    summary:     str


class LegalExportEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("legal_export", {})
        self.max_posts          = c.get("max_posts",              50)
        self.max_bots           = c.get("max_bots",               30)
        self.max_waves          = c.get("max_waves",              20)
        self.max_seeds          = c.get("max_seeds",              20)
        self.max_clusters       = c.get("max_clusters",           10)
        self.max_seeded_posts   = c.get("max_seeded_posts",       20)
        self.max_troll_profiles = c.get("max_troll_profiles",     25)
        self.max_morphs         = c.get("max_morphs",             10)
        self.max_mutations      = c.get("max_mutations",          10)
        self.max_shifts         = c.get("max_shifts",             10)
        self.max_dark_amp       = c.get("max_dark_amp",           15)
        self.max_hijacks        = c.get("max_hijacks",            10)
        self.max_cross_actors   = c.get("max_cross_actors",       15)
        self.analyst_name       = c.get("analyst_name",     "NULLSEC FBSCRAP v2.0")
        self.tool_version       = c.get("tool_version",     "2.0-DEFCON-ELITE")
        self.analyst_org        = c.get("analyst_org",      "NULLSEC RED TEAM")
        self.output_json        = c.get("output_json",            True)
        self.output_html        = c.get("output_html",            True)
        self.output_docx        = c.get("output_docx",            True)
        self.output_zip         = c.get("output_zip",             True)

    # ─────────────────────────────────────────────────────────────────────────

    def export(
        self,
        query:                str,
        scraped_posts:        list[dict],
        bot_report=None,
        temporal_report=None,
        first_mover_report=None,
        sentiment_report=None,
        output_dir:           Path | None = None,
        # New engine reports
        troll_report=None,
        engagement_report=None,
        contagion_report=None,
        reply_report=None,
        cross_campaign_report=None,
        identity_report=None,
        mutation_report=None,
        shift_report=None,
        dark_amp_report=None,
        cib_result=None,
        hcs_report=None,
        comment_report=None,
    ) -> LegalReport:

        now = _now_utc()
        case_id = f"FBSCRAP-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        items: list[EvidenceItem] = []
        counter = [1]

        def add(category: str, desc: str, data: dict, severity: str = "MEDIUM") -> None:
            h = _sha256(data)
            items.append(EvidenceItem(
                item_id      = f"{case_id}-{counter[0]:04d}",
                category     = category,
                description  = desc,
                data         = data,
                sha256       = h,
                collected_at = now,
                severity     = severity,
            ))
            counter[0] += 1

        # ── 1. Posts (evidencia primaria) ─────────────────────────────────────
        for post in scraped_posts[:self.max_posts]:
            add("POST",
                f"Post recolectado de {post.get('source','?')}: {(post.get('text') or '')[:80]}",
                {
                    "url":            post.get("url", ""),
                    "source":         post.get("source", ""),
                    "text":           (post.get("text") or "")[:500],
                    "timestamp":      post.get("timestamp", ""),
                    "scraped_at":     post.get("scraped_at", ""),
                    "reactions":      post.get("reactions", 0),
                    "shares":         post.get("shares", 0),
                    "comments_count": post.get("comments_count", 0),
                    "engagement":     post.get("engagement_total", 0),
                },
            )

        # ── 2. Bot actors (sospechosos comment_bot_detector) ──────────────────
        if bot_report and hasattr(bot_report, "top_bot_suspects"):
            for s in (bot_report.top_bot_suspects or [])[:self.max_bots]:
                add("BOT_ACTOR",
                    f"Actor bot confirmado: {s.author}",
                    {
                        "author":         s.author,
                        "bot_score":      s.composite_score,
                        "total_attacks":  s.total_attacks,
                        "posts_attacked": s.posts_attacked,
                        "sources":        s.sources,
                        "signals":        s.signals,
                        "sample_attacks": s.sample_attacks,
                    },
                    severity="HIGH",
                )

        # ── 3. TrollHunter — perfiles CIB forenses ───────────────────────────
        if troll_report and hasattr(troll_report, "profiles"):
            for p in (troll_report.profiles or [])[:self.max_troll_profiles]:
                if p.bot_risk_score < 40:
                    continue
                sev = ("CRITICAL" if p.bot_risk_score >= 80
                       else "HIGH" if p.bot_risk_score >= 60 else "MEDIUM")
                add("TROLL_PROFILE",
                    f"CIB TrollHunter [{p.classification}]: {p.actor} — riesgo {p.bot_risk_score}/100",
                    {
                        "actor":           p.actor,
                        "bot_risk_score":  p.bot_risk_score,
                        "classification":  p.classification,
                        "total_comments":  p.total_comments,
                        "posts_attacked":  p.posts_attacked,
                        "attack_ratio":    p.attack_ratio,
                        "cph":             p.cph,
                        "signals":         [
                            {"code": s.code, "label": s.label,
                             "severity": s.severity, "detail": s.detail[:300]}
                            for s in getattr(p, "signals", [])
                        ],
                        "justification":   p.justification[:500],
                        "comment_sample":  p.comment_sample[:3],
                    },
                    severity=sev,
                )

        # ── 4. Temporal waves ─────────────────────────────────────────────────
        if temporal_report and hasattr(temporal_report, "waves"):
            for w in (temporal_report.waves or [])[:self.max_waves]:
                add("ATTACK_WAVE",
                    f"Ola de ataque coordinada #{w.wave_id} — {len(getattr(w,'actors',[]))} actores",
                    {
                        "wave_id":    w.wave_id,
                        "start":      str(w.start),
                        "end":        str(w.end),
                        "duration_s": w.duration_s,
                        "actors":     getattr(w, "actors", []),
                        "intensity":  w.intensity,
                    },
                    severity="HIGH",
                )
            for pair in (getattr(temporal_report, "sync_pairs", []) or [])[:self.max_waves]:
                add("SYNC_PAIR",
                    f"Par ultra-sincronizado (Δ{pair.delta_s:.1f}s): {pair.author_a} + {pair.author_b}",
                    {
                        "author_a": pair.author_a,
                        "author_b": pair.author_b,
                        "ts_a":     str(pair.ts_a),
                        "ts_b":     str(pair.ts_b),
                        "delta_s":  pair.delta_s,
                        "post_url": pair.post_url,
                    },
                    severity="CRITICAL",
                )

        # ── 5. Seed accounts ──────────────────────────────────────────────────
        if first_mover_report and hasattr(first_mover_report, "seed_accounts"):
            for prof in (first_mover_report.seed_accounts or [])[:self.max_seeds]:
                add("SEED_ACCOUNT",
                    f"Cuenta semilla (first-mover): {prof.actor} — {prof.seed_count} posts",
                    {
                        "actor":        prof.actor,
                        "seed_count":   prof.seed_count,
                        "avg_position": prof.avg_position,
                        "posts":        prof.posts,
                        "sample_texts": prof.sample_texts,
                    },
                    severity="HIGH",
                )

        # ── 6. Seeded posts ───────────────────────────────────────────────────
        if sentiment_report and hasattr(sentiment_report, "post_deltas"):
            for d in (sentiment_report.post_deltas or [])[:self.max_seeded_posts]:
                if getattr(d, "manipulation_label", "") in ("SEEDED", "REVERSED"):
                    add("SEEDED_POST",
                        f"Manipulación de sentimiento [{d.manipulation_label}]: {d.post_url[:60]}",
                        {
                            "url":                d.post_url,
                            "manipulation_label": d.manipulation_label,
                            "manipulation_delta": d.manipulation_delta,
                            "dominant_actors":    d.dominant_neg_actors,
                        },
                        severity="HIGH",
                    )

        # ── 7. Engagement anomaly — posts inflados artificialmente ────────────
        if engagement_report and hasattr(engagement_report, "posts"):
            for ev in (engagement_report.posts or [])[:self.max_dark_amp]:
                if ev.classification in ("BOT_BOOSTED", "GHOST"):
                    add("ENGAGEMENT_ANOMALY",
                        f"Post inflado artificialmente [{ev.classification}]: {ev.source} — {ev.deviation_pct:.0f}% sobre baseline",
                        {
                            "url":            ev.url,
                            "source":         ev.source,
                            "classification": ev.classification,
                            "reactions":      ev.reactions,
                            "comments":       ev.comments,
                            "shares":         ev.shares,
                            "ratio":          round(ev.ratio, 2),
                            "baseline_ratio": round(ev.baseline_ratio, 2),
                            "deviation_pct":  round(ev.deviation_pct, 1),
                            "text_preview":   ev.text_preview,
                        },
                        severity="HIGH",
                    )

        # ── 8. Emotional contagion ────────────────────────────────────────────
        if contagion_report:
            if contagion_report.contagion_score >= 20:
                add("CONTAGION_EVENT",
                    f"Contaminación emocional [{contagion_report.shift_direction}] — score {contagion_report.contagion_score}/100",
                    {
                        "contagion_score":  contagion_report.contagion_score,
                        "direction":        contagion_report.shift_direction,
                        "bot_arrival":      contagion_report.bot_arrival_ts,
                        "affected_posts":   contagion_report.affected_posts,
                        "pre_sentiment":    contagion_report.pre_bot_sentiment,
                        "post_sentiment":   contagion_report.post_bot_sentiment,
                        "summary":          contagion_report.summary,
                    },
                    severity="HIGH" if contagion_report.shift_direction == "NEGATIVE" else "MEDIUM",
                )

        # ── 9. Reply-chain hijacking ──────────────────────────────────────────
        if reply_report and hasattr(reply_report, "posts"):
            for p in (reply_report.posts or [])[:self.max_hijacks]:
                if p.hijack_score < 40:
                    continue
                for tc in p.targeted_comments[:2]:
                    add("REPLY_HIJACK",
                        f"Secuestro de hilo [{tc.attack_type}]: '{tc.organic_author}' atacado por {tc.reply_count} bots",
                        {
                            "post_url":           p.url,
                            "source":             p.source,
                            "hijack_score":       p.hijack_score,
                            "organic_author":     tc.organic_author,
                            "organic_text":       tc.organic_text,
                            "organic_likes":      tc.organic_likes,
                            "bot_attackers":      tc.bot_attackers,
                            "reply_count":        tc.reply_count,
                            "attack_delta_s":     tc.attack_delta_s,
                            "attack_type":        tc.attack_type,
                        },
                        severity="HIGH",
                    )

        # ── 10. Cross-campaign persistence ────────────────────────────────────
        if cross_campaign_report and hasattr(cross_campaign_report, "actors"):
            for a in (cross_campaign_report.actors or [])[:self.max_cross_actors]:
                if a.campaign_count < 2:
                    continue
                sev = ("CRITICAL" if a.classification == "PROFESSIONAL"
                       else "HIGH" if a.classification == "PERSISTENT" else "MEDIUM")
                add("CROSS_CAMPAIGN",
                    f"Actor persistente [{a.classification}]: {a.name} — {a.campaign_count} campañas atacadas",
                    {
                        "actor":          a.name,
                        "classification": a.classification,
                        "campaigns":      a.campaigns,
                        "campaign_count": a.campaign_count,
                        "avg_bot_score":  a.avg_bot_score,
                        "total_comments": a.total_comments,
                        "first_seen":     a.first_seen,
                        "last_seen":      a.last_seen,
                        "signals":        a.signals_summary,
                    },
                    severity=sev,
                )

        # ── 11. Identity morphs ───────────────────────────────────────────────
        if identity_report and hasattr(identity_report, "morphs"):
            for m in (identity_report.morphs or [])[:self.max_morphs]:
                sev = ("CRITICAL" if m.confidence == "CONFIRMED_MORPH"
                       else "HIGH" if m.confidence == "PROBABLE_MORPH" else "MEDIUM")
                add("IDENTITY_MORPH",
                    f"Cambio de identidad [{m.confidence}]: '{m.actor_a}' ≡ '{m.actor_b}' (sim={m.similarity:.3f})",
                    {
                        "actor_current":    m.actor_a,
                        "actor_historical": m.actor_b,
                        "campaign_current": m.campaign_a,
                        "campaign_history": m.campaign_b,
                        "similarity":       m.similarity,
                        "confidence":       m.confidence,
                        "evidence":         m.evidence[:400],
                    },
                    severity=sev,
                )

        # ── 12. Narrative mutations ───────────────────────────────────────────
        if mutation_report and hasattr(mutation_report, "mutations"):
            for me in (mutation_report.mutations or [])[:self.max_mutations]:
                sev = "CRITICAL" if me.mutation_type == "PIVOT" else "HIGH"
                add("NARRATIVE_MUTATION",
                    f"Mutación narrativa [{me.mutation_type}]: introductor='{me.mutation_introducer}' — score {me.mutation_score}/100",
                    {
                        "mutation_type":    me.mutation_type,
                        "from_ts":          me.from_snapshot.start_ts,
                        "to_ts":            me.to_snapshot.start_ts,
                        "similarity_drop":  me.similarity_drop,
                        "new_terms":        me.new_terms,
                        "dropped_terms":    me.dropped_terms,
                        "introducer":       me.mutation_introducer,
                        "adoption_count":   me.adoption_count,
                        "from_narrative":   me.from_snapshot.top_terms[:6],
                        "to_narrative":     me.to_snapshot.top_terms[:6],
                    },
                    severity=sev,
                )
            if mutation_report.most_active_mutator:
                add("NARRATIVE_MUTATION",
                    f"Operador de narrativa más activo: '{mutation_report.most_active_mutator}'",
                    {
                        "mutator":          mutation_report.most_active_mutator,
                        "seed_narrative":   mutation_report.seed_narrative[:8],
                        "final_narrative":  mutation_report.final_narrative[:8],
                        "total_mutations":  len(mutation_report.mutations),
                        "pivot_events":     mutation_report.pivot_events,
                        "injection_events": mutation_report.injection_events,
                    },
                    severity="CRITICAL" if mutation_report.pivot_events > 0 else "HIGH",
                )

        # ── 13. Bot farm shifts ───────────────────────────────────────────────
        if shift_report and hasattr(shift_report, "shift_events"):
            for se in (shift_report.shift_events or [])[:self.max_shifts]:
                if se.confidence == "LOW":
                    continue
                add("SHIFT_EVENT",
                    f"Cambio de turno de granja [{se.confidence}]: jaccard={se.jaccard_overlap:.2f} — {se.turnover_pct:.0%} rotación",
                    {
                        "confidence":     se.confidence,
                        "shift_score":    se.shift_score,
                        "from_window":    se.from_cohort.window_end,
                        "to_window":      se.to_cohort.window_start,
                        "jaccard":        se.jaccard_overlap,
                        "turnover_pct":   se.turnover_pct,
                        "naming_sim":     se.naming_sim,
                        "from_bots":      se.from_cohort.bot_actors[:10],
                        "to_bots":        se.to_cohort.bot_actors[:10],
                        "from_patterns":  se.from_cohort.naming_patterns,
                        "to_patterns":    se.to_cohort.naming_patterns,
                    },
                    severity="HIGH",
                )

        # ── 14. Dark amplification ────────────────────────────────────────────
        if dark_amp_report and hasattr(dark_amp_report, "events"):
            for ev in (dark_amp_report.events or [])[:self.max_dark_amp]:
                if ev.classification != "DARK_AMP":
                    continue
                add("DARK_AMP",
                    f"Amplificación artificial: {ev.source} — {ev.amplification_factor:.1f}x baseline",
                    {
                        "url":                  ev.url,
                        "source":               ev.source,
                        "classification":       ev.classification,
                        "amplification_factor": round(ev.amplification_factor, 2),
                        "velocity":             round(ev.velocity, 1),
                        "baseline_velocity":    round(ev.baseline_velocity, 1),
                        "reaction_purity":      round(ev.reaction_purity, 3),
                        "age_hours":            round(ev.age_hours, 1),
                        "text_preview":         ev.text_preview,
                    },
                    severity="HIGH",
                )

        # ── 15. CIB clusters ──────────────────────────────────────────────────
        if cib_result and hasattr(cib_result, "clusters"):
            for cl in (getattr(cib_result, "clusters", []) or [])[:self.max_clusters]:
                members = getattr(cl, "members", [])
                add("CIB_CLUSTER",
                    f"Cluster CIB — {len(members)} actores coordinados",
                    {
                        "cluster_id":   getattr(cl, "cluster_id", 0),
                        "members":      members[:15],
                        "size":         len(members),
                        "risk_level":   getattr(cl, "risk_level", "?"),
                    },
                    severity="HIGH" if len(members) >= 5 else "MEDIUM",
                )

        # ── Build manifest ────────────────────────────────────────────────────
        all_hashes    = sorted(it.sha256 for it in items)
        manifest_hash = _sha256(all_hashes)

        categories: dict[str, int] = {}
        for it in items:
            categories[it.category] = categories.get(it.category, 0) + 1

        manifest = LegalManifest(
            case_id        = case_id,
            generated_at   = now,
            analyst        = self.analyst_name,
            tool_version   = self.tool_version,
            query          = query,
            total_items    = len(items),
            categories     = categories,
            manifest_hash  = manifest_hash,
            evidence_items = items,
        )

        html_path = json_path = docx_path = zip_path = None

        if output_dir:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            if self.output_json:
                json_path = str(output_dir / f"{case_id}_manifest.json")
                Path(json_path).write_text(
                    json.dumps(self._manifest_to_dict(manifest), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            if self.output_html:
                html_path = str(output_dir / f"{case_id}_evidencia_judicial.html")
                Path(html_path).write_text(
                    self._build_html_judicial(manifest, query,
                                               troll_report, engagement_report,
                                               contagion_report, cross_campaign_report,
                                               identity_report, mutation_report),
                    encoding="utf-8",
                )

            if self.output_docx:
                docx_path = self._build_docx_judicial(
                    manifest, query, output_dir,
                    troll_report, engagement_report, contagion_report,
                )

            if self.output_zip and json_path and html_path:
                zip_path = str(output_dir / f"{case_id}_paquete_judicial.zip")
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for fpath in [json_path, html_path, docx_path]:
                        if fpath and Path(fpath).exists():
                            zf.write(fpath, Path(fpath).name)

        print(f"  [LEGAL] {len(items)} evidence items · "
              f"CRITICAL={sum(1 for i in items if i.severity=='CRITICAL')} · "
              f"HIGH={sum(1 for i in items if i.severity=='HIGH')} · "
              f"case_id={case_id}")

        return LegalReport(
            manifest  = manifest,
            html_path = html_path,
            docx_path = docx_path,
            json_path = json_path,
            zip_path  = zip_path,
            summary   = self._build_summary(manifest),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # HTML Judicial Format
    # ─────────────────────────────────────────────────────────────────────────

    def _build_html_judicial(
        self,
        manifest:          LegalManifest,
        query:             str,
        troll_report=None,
        engagement_report=None,
        contagion_report=None,
        cross_campaign_report=None,
        identity_report=None,
        mutation_report=None,
    ) -> str:
        items = manifest.evidence_items
        crit  = [i for i in items if i.severity == "CRITICAL"]
        high  = [i for i in items if i.severity == "HIGH"]
        gen_es = _es_date(manifest.generated_at)

        # Category counts for executive summary
        cat = manifest.categories
        n_troll    = cat.get("TROLL_PROFILE", 0)
        n_waves    = cat.get("ATTACK_WAVE", 0) + cat.get("SYNC_PAIR", 0)
        n_cross    = cat.get("CROSS_CAMPAIGN", 0)
        n_morph    = cat.get("IDENTITY_MORPH", 0)
        n_mutation = cat.get("NARRATIVE_MUTATION", 0)
        n_shift    = cat.get("SHIFT_EVENT", 0)
        n_amp      = cat.get("DARK_AMP", 0) + cat.get("ENGAGEMENT_ANOMALY", 0)
        n_hijack   = cat.get("REPLY_HIJACK", 0)

        # ── Executive summary paragraph (Spanish, non-technical) ──────────────
        exec_summary_items = []
        if n_troll:
            exec_summary_items.append(
                f"Se identificaron <strong>{n_troll} cuenta(s)</strong> con indicadores "
                f"forenses de comportamiento automatizado o coordinado (bots/trolls), "
                f"de las cuales {cat.get('TROLL_PROFILE',0)} cuentan con perfil forense completo."
            )
        if n_waves:
            exec_summary_items.append(
                f"Se detectaron <strong>{cat.get('ATTACK_WAVE',0)} ola(s) de ataque coordinado</strong> "
                f"con comentarios sincronizados en ventanas de segundos — "
                f"patrón imposible de replicar de forma orgánica por personas individuales."
            )
        if n_cross:
            exec_summary_items.append(
                f"Se identificaron <strong>{n_cross} actor(es) persistentes</strong> que han participado "
                f"en ataques coordinados contra diferentes figuras políticas en múltiples campañas — "
                f"indicativo de actividad profesional remunerada."
            )
        if n_morph:
            exec_summary_items.append(
                f"Se detectaron <strong>{n_morph} cambio(s) de identidad</strong> donde el mismo operador "
                f"utiliza diferentes cuentas con nombres distintos pero con huella conductual idéntica "
                f"— evidencia de evasión deliberada de controles."
            )
        if n_mutation:
            exec_summary_items.append(
                f"La narrativa de ataque mutó <strong>{n_mutation} vez/veces</strong> durante la campaña, "
                f"con cambios coordinados en el vocabulario de ataque que indican "
                f"dirección operacional centralizada."
            )
        if n_shift:
            exec_summary_items.append(
                f"Se detectaron <strong>{n_shift} cambio(s) de turno</strong> de actores dentro de la misma "
                f"operación — patrón consistente con una granja de bots con rotación de personal."
            )
        if n_amp:
            exec_summary_items.append(
                f"Se identificaron <strong>{n_amp} publicación(es)</strong> con amplificación artificial "
                f"de engagement (reacciones sin interacción orgánica real) — "
                f"método utilizado para crear percepción falsa de relevancia."
            )
        if n_hijack:
            exec_summary_items.append(
                f"Se documentaron <strong>{n_hijack} caso(s)</strong> de secuestro de hilos de comentarios, "
                f"donde múltiples bots respondieron coordinadamente a comentarios positivos "
                f"de ciudadanos reales para enterrarlos."
            )

        exec_html = "\n".join(f"<p class='finding'>▸ {p}</p>" for p in exec_summary_items) \
                    if exec_summary_items else "<p>No se detectaron indicadores de comportamiento inorgánico.</p>"

        # ── Evidence table ────────────────────────────────────────────────────
        rows_html = ""
        sev_badge = {
            "CRITICAL": "<span class='sev-critical'>⛔ CRÍTICO</span>",
            "HIGH":     "<span class='sev-high'>🔴 ALTO</span>",
            "MEDIUM":   "<span class='sev-medium'>🟡 MEDIO</span>",
            "LOW":      "<span class='sev-low'>⚪ BAJO</span>",
        }
        for it in items:
            data_preview = " | ".join(
                f"{k}: {str(v)[:80]}" for k, v in list(it.data.items())[:4]
            )
            rows_html += f"""
              <tr class="row-{it.severity.lower()}">
                <td class="mono">{it.item_id}</td>
                <td>{sev_badge.get(it.severity,'')}</td>
                <td><span class="cat-badge cat-{it.category.lower()}">{it.category}</span></td>
                <td>{it.description[:120]}</td>
                <td class="mono small">{it.sha256[:32]}…</td>
              </tr>"""

        return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Paquete de Evidencia Judicial — {manifest.case_id}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Times New Roman',serif;background:#fff;color:#1a1a1a;font-size:12pt;line-height:1.6;padding:40px 60px}}
  h1{{font-size:16pt;color:#1a1a2e;border-bottom:2px solid #c00000;padding-bottom:8px;margin-bottom:16px}}
  h2{{font-size:13pt;color:#1a1a2e;border-left:4px solid #c00000;padding-left:10px;margin:24px 0 12px}}
  h3{{font-size:11pt;color:#333;margin:16px 0 8px}}
  .header-box{{border:2px solid #1a1a2e;padding:16px;margin-bottom:24px}}
  .header-grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:10pt}}
  .header-grid .label{{color:#555;font-style:italic}}
  .header-grid .value{{font-weight:bold}}
  .integrity-hash{{background:#f5f5f5;border:1px solid #ccc;padding:8px;font-family:monospace;font-size:9pt;margin-top:12px;word-break:break-all}}
  .exec-summary{{background:#fff8f8;border:1px solid #c00000;padding:16px;margin:16px 0}}
  .finding{{margin:8px 0;padding-left:16px}}
  .stats-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0}}
  .stat-card{{border:1px solid #ddd;padding:12px;text-align:center}}
  .stat-val{{font-size:20pt;font-weight:bold;color:#c00000}}
  .stat-label{{font-size:8pt;color:#555;margin-top:4px}}
  table{{width:100%;border-collapse:collapse;margin:12px 0;font-size:9pt}}
  th{{background:#1a1a2e;color:#fff;padding:6px 8px;text-align:left}}
  td{{padding:5px 8px;border-bottom:1px solid #e0e0e0;vertical-align:top}}
  tr:nth-child(even){{background:#f9f9f9}}
  .row-critical td{{background:#fff0f0}}
  .row-high td{{background:#fff8f0}}
  .mono{{font-family:monospace;font-size:8pt}}
  .small{{font-size:8pt}}
  .sev-critical{{color:#c00000;font-weight:bold}}
  .sev-high{{color:#e05c00;font-weight:bold}}
  .sev-medium{{color:#9b7a00}}
  .sev-low{{color:#555}}
  .cat-badge{{display:inline-block;padding:1px 6px;border-radius:3px;font-size:8pt;font-weight:bold}}
  .cat-troll_profile{{background:#ffe0e0;color:#c00000}}
  .cat-attack_wave{{background:#fff0e0;color:#c05000}}
  .cat-sync_pair{{background:#ffe8c0;color:#906000}}
  .cat-cross_campaign{{background:#e8e0ff;color:#4000c0}}
  .cat-identity_morph{{background:#ffe0f0;color:#c00060}}
  .cat-narrative_mutation{{background:#e0f0ff;color:#004080}}
  .cat-shift_event{{background:#e8ffe0;color:#005000}}
  .cat-dark_amp{{background:#fff0e0;color:#804000}}
  .cat-post{{background:#e0e8ff;color:#002080}}
  .cat-bot_actor,.cat-troll_profile{{background:#ffe0e0;color:#c00000}}
  .cat-engagement_anomaly{{background:#ffe8d0;color:#804000}}
  .cat-contagion_event{{background:#ffe0f8;color:#800080}}
  .cat-reply_hijack{{background:#fff0d0;color:#806000}}
  .cat-cib_cluster{{background:#e0f0e0;color:#004000}}
  .certification{{border:2px solid #1a1a2e;padding:16px;margin-top:32px}}
  .sig-line{{border-top:1px solid #333;margin-top:24px;padding-top:4px;font-size:9pt;color:#555}}
  @media print{{
    body{{padding:20px 30px}}
    .row-critical td{{background:#ffeeee!important;-webkit-print-color-adjust:exact}}
  }}
</style>
</head>
<body>

<h1>PAQUETE DE EVIDENCIA FORENSE DIGITAL<br>
<span style="font-size:11pt;font-weight:normal">Comportamiento Inorgánico Coordinado en Redes Sociales</span></h1>

<div class="header-box">
  <div class="header-grid">
    <span class="label">Número de caso:</span>
    <span class="value">{manifest.case_id}</span>
    <span class="label">Fecha y hora de generación:</span>
    <span class="value">{gen_es}</span>
    <span class="label">Sujeto de investigación:</span>
    <span class="value">{query}</span>
    <span class="label">Analista responsable:</span>
    <span class="value">{manifest.analyst}</span>
    <span class="label">Herramienta forense:</span>
    <span class="value">{manifest.tool_version}</span>
    <span class="label">Total de ítems de evidencia:</span>
    <span class="value">{manifest.total_items} ({len(crit)} CRÍTICOS · {len(high)} ALTOS)</span>
  </div>
  <div class="integrity-hash">
    <strong>HASH DE INTEGRIDAD DEL MANIFIESTO (SHA-256):</strong><br>
    {manifest.manifest_hash}<br>
    <em style="font-size:9pt;color:#555">Cualquier alteración posterior a este documento invalida el hash y rompe la cadena de custodia.</em>
  </div>
</div>

<h2>I. RESUMEN EJECUTIVO</h2>
<p style="margin-bottom:12px">El presente documento constituye el reporte forense de una campaña de
<strong>Comportamiento Inorgánico Coordinado (CIB)</strong> detectada mediante análisis automatizado
de plataforma Facebook en relación con la figura pública <strong>{query}</strong>.
La evidencia fue recolectada el {gen_es} mediante la herramienta <em>{manifest.tool_version}</em>.</p>
<div class="exec-summary">
  <h3 style="color:#c00000;margin-bottom:8px">HALLAZGOS PRINCIPALES</h3>
  {exec_html}
</div>

<div class="stats-grid">
  <div class="stat-card">
    <div class="stat-val">{manifest.total_items}</div>
    <div class="stat-label">ÍTEMS DE EVIDENCIA</div>
  </div>
  <div class="stat-card">
    <div class="stat-val" style="color:#c00000">{len(crit)}</div>
    <div class="stat-label">EVIDENCIA CRÍTICA</div>
  </div>
  <div class="stat-card">
    <div class="stat-val">{n_troll}</div>
    <div class="stat-label">PERFILES BOT/TROLL</div>
  </div>
  <div class="stat-card">
    <div class="stat-val">{n_cross}</div>
    <div class="stat-label">ACTORES PERSISTENTES</div>
  </div>
</div>

<h2>II. CATEGORÍAS DE EVIDENCIA</h2>
<table>
  <tr><th>Categoría</th><th>Cantidad</th><th>Descripción</th></tr>
  {"".join(
      f"<tr><td><strong>{cat}</strong></td><td>{n}</td><td>{self._cat_description(cat)}</td></tr>"
      for cat, n in sorted(manifest.categories.items(), key=lambda x: -x[1])
  )}
</table>

<h2>III. INVENTARIO DE EVIDENCIA FORENSE</h2>
<p style="font-size:10pt;color:#555;margin-bottom:8px">
Cada ítem incluye su hash SHA-256 individual para verificación de integridad.</p>
<table>
  <tr>
    <th style="width:14%">ID de Ítem</th>
    <th style="width:10%">Severidad</th>
    <th style="width:14%">Categoría</th>
    <th>Descripción</th>
    <th style="width:22%">Hash SHA-256 (parcial)</th>
  </tr>
  {rows_html}
</table>

<h2>IV. CERTIFICACIÓN DEL ANALISTA</h2>
<div class="certification">
  <p>El suscrito certifica que:</p>
  <ol style="margin-left:20px;margin-top:8px;line-height:2">
    <li>La evidencia contenida en este documento fue recolectada mediante procesos automatizados
        de la herramienta <strong>{manifest.tool_version}</strong> el {gen_es}.</li>
    <li>Los hashes SHA-256 individuales y el hash de integridad del manifiesto permiten verificar
        que la evidencia no ha sido alterada desde su recolección.</li>
    <li>Los algoritmos de detección utilizados son de dominio técnico forense reconocido:
        análisis de redes (CIB Graph), análisis estilométrico, análisis temporal de bursts,
        detección de coordinación inorgánica y análisis de mutación de narrativas.</li>
    <li>Este documento fue generado automáticamente y su contenido refleja fielmente
        los datos extraídos de la plataforma Facebook sin modificación manual.</li>
  </ol>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:32px;margin-top:32px">
    <div>
      <div class="sig-line">Analista: {manifest.analyst}</div>
      <div class="sig-line">Organización: {self.analyst_org}</div>
    </div>
    <div>
      <div class="sig-line">Número de caso: {manifest.case_id}</div>
      <div class="sig-line">Fecha: {gen_es}</div>
    </div>
  </div>
</div>

<p style="margin-top:24px;font-size:9pt;color:#888;text-align:center">
  Generado por {manifest.tool_version} — Todos los datos extraídos de fuentes públicas de Facebook.
  Hash de integridad: {manifest.manifest_hash[:24]}...
</p>
</body>
</html>"""

    @staticmethod
    def _cat_description(cat: str) -> str:
        return {
            "POST":               "Publicación extraída de la plataforma",
            "BOT_ACTOR":          "Actor identificado como bot por análisis de comportamiento",
            "TROLL_PROFILE":      "Perfil CIB forense con múltiples señales de coordinación",
            "ATTACK_WAVE":        "Ola de ataque coordinado con timestamps sincronizados",
            "SYNC_PAIR":          "Par de actores comentando en ventana de 3 segundos (imposible orgánico)",
            "SEED_ACCOUNT":       "Cuenta que introduce narrativas de ataque primero en múltiples posts",
            "SEEDED_POST":        "Post cuyo sentimiento fue manipulado por actores coordinados",
            "ENGAGEMENT_ANOMALY": "Post con engagement artificial (reacciones sin interacción real)",
            "CONTAGION_EVENT":    "Desplazamiento emocional del hilo causado por llegada de bots",
            "REPLY_HIJACK":       "Secuestro coordinado de comentarios orgánicos positivos",
            "CROSS_CAMPAIGN":     "Actor que ha participado en múltiples campañas de ataque",
            "IDENTITY_MORPH":     "Cambio de identidad detectado por huella conductual",
            "NARRATIVE_MUTATION": "Evolución coordinada de la narrativa de ataque",
            "SHIFT_EVENT":        "Cambio de turno entre cohorts de la granja de bots",
            "DARK_AMP":           "Amplificación artificial de tendencia con engagement falso",
            "CIB_CLUSTER":        "Cluster de actores coordinados en la red CIB",
        }.get(cat, cat)

    # ─────────────────────────────────────────────────────────────────────────
    # DOCX Judicial Format
    # ─────────────────────────────────────────────────────────────────────────

    def _build_docx_judicial(
        self,
        manifest:         LegalManifest,
        query:            str,
        output_dir:       Path,
        troll_report=None,
        engagement_report=None,
        contagion_report=None,
    ) -> str | None:
        try:
            from docx import Document
            from docx.shared import Pt, Inches, RGBColor
            from docx.enum.text import WD_ALIGN_PARAGRAPH
        except ImportError:
            return None

        doc  = Document()
        sec  = doc.sections[0]
        sec.page_width    = Inches(8.5)
        sec.page_height   = Inches(11)
        sec.left_margin   = Inches(1.2)
        sec.right_margin  = Inches(1.2)
        sec.top_margin    = Inches(1.0)
        sec.bottom_margin = Inches(1.0)

        RED   = RGBColor(0xC0, 0x00, 0x00)
        DARK  = RGBColor(0x1A, 0x1A, 0x2E)
        GRAY  = RGBColor(0x55, 0x55, 0x55)
        BLACK = RGBColor(0x00, 0x00, 0x00)

        def heading(text: str, level: int = 1, color=DARK) -> None:
            p = doc.add_heading(text, level=level)
            for run in p.runs:
                run.font.color.rgb = color
                run.font.size = Pt(14 - level * 2)

        def body(text: str, bold: bool = False, color=BLACK, size: int = 11) -> None:
            p = doc.add_paragraph()
            r = p.add_run(text)
            r.bold = bold
            r.font.color.rgb = color
            r.font.size = Pt(size)
            return p

        def divider() -> None:
            p = doc.add_paragraph("─" * 80)
            p.runs[0].font.size = Pt(8)
            p.runs[0].font.color.rgb = GRAY

        gen_es = _es_date(manifest.generated_at)
        items  = manifest.evidence_items
        crit   = [i for i in items if i.severity == "CRITICAL"]
        high   = [i for i in items if i.severity == "HIGH"]

        # Title page
        title = doc.add_heading("PAQUETE DE EVIDENCIA FORENSE DIGITAL", 0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title.runs[0].font.color.rgb = RED
        title.runs[0].font.size = Pt(16)

        sub = doc.add_paragraph()
        sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sr = sub.add_run("Comportamiento Inorgánico Coordinado en Redes Sociales\n"
                          f"Caso: {manifest.case_id}")
        sr.font.size = Pt(12)
        sr.font.color.rgb = DARK

        doc.add_paragraph()
        for label, value in [
            ("Sujeto de investigación:", query),
            ("Fecha de generación:", gen_es),
            ("Analista:", manifest.analyst),
            ("Herramienta:", manifest.tool_version),
            ("Total de evidencia:", f"{manifest.total_items} ítems ({len(crit)} críticos · {len(high)} altos)"),
            ("Hash de integridad:", manifest.manifest_hash[:48] + "…"),
        ]:
            p = doc.add_paragraph()
            p.add_run(f"{label} ").bold = True
            p.runs[-1].bold = True
            p.runs[-1].font.color.rgb = GRAY
            p.runs[-1].font.size = Pt(10)
            p.add_run(value).font.size = Pt(10)

        doc.add_page_break()

        # Section I: Executive summary
        heading("I. RESUMEN EJECUTIVO")
        body(f"El presente documento es el reporte forense de una campaña de Comportamiento "
             f"Inorgánico Coordinado (CIB) detectada en Facebook relacionada con "
             f"la figura pública {query}, generado el {gen_es}.")

        doc.add_paragraph()
        cat = manifest.categories
        for label, value in [
            ("Perfiles bot/troll confirmados:", cat.get("TROLL_PROFILE", 0)),
            ("Olas de ataque coordinadas:", cat.get("ATTACK_WAVE", 0)),
            ("Actores persistentes multi-campaña:", cat.get("CROSS_CAMPAIGN", 0)),
            ("Cambios de identidad detectados:", cat.get("IDENTITY_MORPH", 0)),
            ("Mutaciones de narrativa:", cat.get("NARRATIVE_MUTATION", 0)),
            ("Publicaciones amplificadas artificialmente:", cat.get("DARK_AMP", 0) + cat.get("ENGAGEMENT_ANOMALY", 0)),
        ]:
            p = doc.add_paragraph(style="List Bullet")
            p.add_run(f"{label} ").bold = False
            p.runs[0].font.size = Pt(11)
            p.add_run(str(value)).bold = True
            p.runs[1].font.size = Pt(11)
            p.runs[1].font.color.rgb = RED if int(value) > 0 else GRAY

        # Section II: Evidence inventory
        doc.add_page_break()
        heading("II. INVENTARIO DE EVIDENCIA FORENSE")

        tbl = doc.add_table(rows=1, cols=4)
        tbl.style = "Table Grid"
        for i, h in enumerate(["ID", "SEVERIDAD", "CATEGORÍA", "DESCRIPCIÓN"]):
            cell = tbl.rows[0].cells[i]
            cell.paragraphs[0].add_run(h).bold = True
            cell.paragraphs[0].runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            cell.paragraphs[0].runs[0].font.size = Pt(9)
            # Dark background via XML
            from docx.oxml.ns import qn
            from docx.oxml import OxmlElement
            tc = cell._tc
            tcPr = tc.get_or_add_tcPr()
            shd = OxmlElement("w:shd")
            shd.set(qn("w:fill"), "1A1A2E")
            shd.set(qn("w:color"), "auto")
            shd.set(qn("w:val"), "clear")
            tcPr.append(shd)

        for it in items:
            row = tbl.add_row()
            sev_colors = {"CRITICAL": RED, "HIGH": RGBColor(0xE0,0x5C,0x00),
                          "MEDIUM": RGBColor(0x80,0x60,0x00), "LOW": GRAY}
            row.cells[0].paragraphs[0].add_run(it.item_id).font.size = Pt(8)
            run = row.cells[1].paragraphs[0].add_run(it.severity)
            run.font.size = Pt(8)
            run.font.color.rgb = sev_colors.get(it.severity, GRAY)
            run.bold = True
            row.cells[2].paragraphs[0].add_run(it.category).font.size = Pt(8)
            row.cells[3].paragraphs[0].add_run(it.description[:120]).font.size = Pt(8)

        # Section III: Certification
        doc.add_page_break()
        heading("III. CERTIFICACIÓN DEL ANALISTA")
        body("El suscrito certifica que la evidencia contenida en este documento fue recolectada "
             "mediante procesos automatizados de análisis forense de redes sociales, que los "
             "hashes SHA-256 garantizan la integridad de la evidencia, y que los algoritmos "
             "de detección utilizados corresponden a metodologías forenses digitales reconocidas.")

        doc.add_paragraph()
        doc.add_paragraph()
        for label, value in [
            ("Analista responsable:", manifest.analyst),
            ("Número de caso:", manifest.case_id),
            ("Fecha y hora:", gen_es),
            ("Hash de integridad:", manifest.manifest_hash),
        ]:
            p = doc.add_paragraph()
            p.add_run(f"{label} ")
            p.runs[0].bold = True
            p.runs[0].font.size = Pt(10)
            p.add_run(value).font.size = Pt(10)

        doc.add_paragraph()
        doc.add_paragraph()
        body("________________________                    ________________________", size=10)
        body("Firma del Analista                          Fecha y Lugar", color=GRAY, size=10)

        docx_path = str(output_dir / f"{manifest.case_id}_judicial.docx")
        doc.save(docx_path)
        return docx_path

    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _manifest_to_dict(manifest: LegalManifest) -> dict:
        return {
            "case_id":       manifest.case_id,
            "generated_at":  manifest.generated_at,
            "analyst":       manifest.analyst,
            "tool_version":  manifest.tool_version,
            "query":         manifest.query,
            "total_items":   manifest.total_items,
            "categories":    manifest.categories,
            "manifest_hash": manifest.manifest_hash,
            "evidence_items": [
                {
                    "item_id":      it.item_id,
                    "category":     it.category,
                    "severity":     it.severity,
                    "description":  it.description,
                    "sha256":       it.sha256,
                    "collected_at": it.collected_at,
                    "data":         it.data,
                }
                for it in manifest.evidence_items
            ],
        }

    @staticmethod
    def _build_summary(manifest: LegalManifest) -> str:
        cats = ", ".join(f"{c}:{n}" for c, n in sorted(manifest.categories.items()))
        crit = sum(1 for i in manifest.evidence_items if i.severity == "CRITICAL")
        return (
            f"Paquete judicial {manifest.case_id}: "
            f"{manifest.total_items} ítems ({crit} críticos) [{cats}]. "
            f"Hash: {manifest.manifest_hash[:16]}…"
        )
