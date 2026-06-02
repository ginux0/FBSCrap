"""
HTML Dashboard Reporter — Obsidian dark theme, self-contained.

Generates a single .html file with:
  • Overview metrics cards
  • CIB Network (D3 force-directed graph, interactive)
  • HCS Distribution (Chart.js bar)
  • Attack Timeline (Chart.js line)
  • Bot Suspects table (sortable, searchable)
  • Ownership Attribution (operator cards + bot-page matrix)
  • All data embedded as JSON — zero external file dependencies at runtime
    (D3 + Chart.js loaded from CDN, gracefully degrades offline)
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .comment_bot_detector import CommentBotReport
    from .bot_detector import BotAnalysisReport
    from .cib_graph import CIBGraphResult
    from .hcs_engine import HCSReport
    from .ownership_engine import OwnershipReport


def generate_html_dashboard(
    posts:              list[dict],
    output_path:        Path,
    query:              str = "",
    comment_report:     "CommentBotReport | None"     = None,
    bot_report:         "BotAnalysisReport | None"    = None,
    cib_result:         "CIBGraphResult | None"       = None,
    hcs_report:         "HCSReport | None"            = None,
    ownership_report:   "OwnershipReport | None"      = None,
    temporal_report:    "TemporalReport | None"       = None,
    stylo_report:       "StylometryReport | None"     = None,
    sentiment_report:   "SentimentDeltaReport | None"   = None,
    first_mover_report: "FirstMoverReport | None"       = None,
    semantic_report:    "SemanticReport | None"         = None,
    legal_report:       "LegalReport | None"            = None,
    lifecycle_report:   "LifecycleReport | None"          = None,
    injection_report:   "NarrativeInjectionReport | None" = None,
    topology_report:    "InfluenceTopologyReport | None"  = None,
    hashtag_report:     "HashtagWeaponizationReport | None" = None,
    velocity_report:    "AccountVelocityReport | None"     = None,
    seeding_report:     "NarrativePropagationReport | None" = None,
    correlation_report: "TimeCorrelationReport | None"     = None,
    attribution_report: "BotOperatorReport | None"         = None,
    troll_report:       "TrollHunterReport | None"          = None,
    engagement_report:     "EngagementAnomalyReport | None"       = None,
    contagion_report:      "EmotionalContagionReport | None"      = None,
    reply_report:          "ReplyChainHijackReport | None"        = None,
    cross_campaign_report: "CrossCampaignReport | None"           = None,
    dark_amp_report:       "DarkAmplificationReport | None"       = None,
    shift_report:          "BotFarmShiftReport | None"            = None,
    identity_report:       "IdentityPersistenceReport | None"     = None,
    mutation_report:       "NarrativeMutationReport | None"       = None,
    cib_score_report=None,
    chain_report=None,
    multi_source_report=None,
    cfg:                   dict | None = None,
) -> None:
    now      = datetime.now()
    date_lbl = now.strftime("%Y-%m-%d %H:%M")
    target   = (query or "ANÁLISIS FBSCRAP").upper()
    total    = len(posts)

    # ── Prepare embedded JSON data ─────────────────────────────────────────────
    cib_d3           = cib_result.d3_json   if cib_result   else {"nodes": [], "links": []}
    hcs_data         = _build_hcs_data(hcs_report)
    timeline         = _build_timeline_data(posts)
    suspects         = _build_suspects_data(comment_report, hcs_report)
    ownership_data   = _build_ownership_data(ownership_report)
    temporal_data    = _build_temporal_data(temporal_report)
    stylo_data       = _build_stylo_data(stylo_report)
    sentiment_data   = _build_sentiment_data(sentiment_report)
    first_mover_data = _build_first_mover_data(first_mover_report)
    semantic_data    = _build_semantic_data(semantic_report)
    legal_data       = _build_legal_data(legal_report)
    lifecycle_data   = _build_lifecycle_data(lifecycle_report)
    injection_data   = _build_injection_data(injection_report)
    topology_data    = _build_topology_data(topology_report)
    hashtag_data     = _build_hashtag_data(hashtag_report)
    velocity_data    = _build_velocity_data(velocity_report)
    seeding_data     = _build_seeding_data(seeding_report)
    correlation_data = _build_correlation_data(correlation_report)
    attribution_data = _build_attribution_data(attribution_report)
    troll_data       = _build_troll_data(troll_report)
    engagement_data      = _build_engagement_data(engagement_report)
    contagion_data       = _build_contagion_data(contagion_report)
    reply_data           = _build_reply_data(reply_report)
    cross_campaign_data  = _build_cross_campaign_data(cross_campaign_report)
    dark_amp_data        = _build_dark_amp_data(dark_amp_report)
    shift_data           = _build_shift_data(shift_report)
    identity_data        = _build_identity_data(identity_report)
    mutation_data        = _build_mutation_data(mutation_report)
    cib_score_data       = _build_cib_score_data(cib_score_report)
    chain_data           = _build_chain_data(chain_report)
    multi_source_data    = _build_multi_source_data(multi_source_report)
    glossary_data        = _build_glossary_data(cfg)
    metrics              = _build_metrics(
        posts, comment_report, cib_result, hcs_report, ownership_report,
        temporal_report, stylo_report, sentiment_report, first_mover_report,
        semantic_report, lifecycle_report, injection_report,
        topology_report, hashtag_report, velocity_report,
        seeding_report, correlation_report, attribution_report,
        troll_report=troll_report,
        engagement_report=engagement_report,
        contagion_report=contagion_report,
        reply_report=reply_report,
        cross_campaign_report=cross_campaign_report,
        dark_amp_report=dark_amp_report,
        shift_report=shift_report,
        identity_report=identity_report,
        mutation_report=mutation_report,
    )

    data_json = json.dumps({
        "target":      target,
        "date":        date_lbl,
        "total":       total,
        "metrics":     metrics,
        "cib":         cib_d3,
        "hcs":         hcs_data,
        "timeline":    timeline,
        "suspects":    suspects,
        "ownership":   ownership_data,
        "temporal":    temporal_data,
        "stylo":       stylo_data,
        "sentiment":   sentiment_data,
        "first_mover": first_mover_data,
        "semantic":    semantic_data,
        "legal":       legal_data,
        "lifecycle":   lifecycle_data,
        "injection":   injection_data,
        "topology":     topology_data,
        "hashtag":      hashtag_data,
        "velocity":     velocity_data,
        "seeding":      seeding_data,
        "correlation":  correlation_data,
        "attribution":  attribution_data,
        "troll":        troll_data,
        "engagement":      engagement_data,
        "contagion":       contagion_data,
        "reply_chain":     reply_data,
        "cross_campaign":  cross_campaign_data,
        "dark_amp":        dark_amp_data,
        "shift":           shift_data,
        "identity":        identity_data,
        "mutation":        mutation_data,
        "cib_score":       cib_score_data,
        "chains":          chain_data,
        "multi_source":    multi_source_data,
        "glossary":        glossary_data,
    }, ensure_ascii=False)

    html = _build_html(target, date_lbl, data_json)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    size_kb = output_path.stat().st_size // 1024
    print(f"  [HTML] → {output_path}  ({size_kb} KB)")


# ── Data builders ─────────────────────────────────────────────────────────────

def _build_metrics(
    posts, comment_report, cib_result, hcs_report,
    ownership_report, temporal_report=None, stylo_report=None,
    sentiment_report=None, first_mover_report=None, semantic_report=None,
    lifecycle_report=None, injection_report=None,
    topology_report=None, hashtag_report=None,
    velocity_report=None, seeding_report=None,
    correlation_report=None, attribution_report=None,
    troll_report=None, engagement_report=None, contagion_report=None,
    reply_report=None, cross_campaign_report=None,
    dark_amp_report=None, shift_report=None,
    identity_report=None, mutation_report=None,
) -> dict:
    total     = len(posts)
    bot_pct   = comment_report.bot_confirmed_pct    if comment_report    else 0
    coord     = cib_result.coordination_score        if cib_result        else 0
    mean_hcs  = hcs_report.mean_hcs                 if hcs_report        else 0
    op_count  = ownership_report.total_operators     if ownership_report  else 0
    atk_pages = ownership_report.total_attack_pages  if ownership_report  else 0
    t_score   = temporal_report.overall_score        if temporal_report   else 0
    t_waves   = len(temporal_report.waves)           if temporal_report   else 0
    s_bots    = len(stylo_report.bot_style_actors)   if stylo_report      else 0
    s_clust   = len(stylo_report.clusters)           if stylo_report      else 0
    sent_score= sentiment_report.manipulation_score  if sentiment_report  else 0
    fm_seeds  = len(sentiment_report.seeded_posts)   if sentiment_report  else 0
    fm_accts  = len(first_mover_report.seed_accounts) if first_mover_report else 0
    narr_score= semantic_report.narrative_score      if semantic_report   else 0
    bot_clust = semantic_report.bot_dominated_count  if semantic_report   else 0
    lc_score  = lifecycle_report.anomaly_score       if lifecycle_report  else 0
    lc_sleep  = len(lifecycle_report.sleepers)       if lifecycle_report  else 0
    lc_cells  = len(lifecycle_report.sleeper_cells)  if lifecycle_report  else 0
    inj_score = injection_report.injection_score     if injection_report  else 0
    inj_count = injection_report.total_narratives    if injection_report  else 0
    top_score = topology_report.influence_score      if topology_report   else 0
    top_gini  = topology_report.pagerank_gini        if topology_report   else 0.0
    ht_score  = hashtag_report.weaponization_score   if hashtag_report    else 0
    ht_weap   = len(hashtag_report.weaponized_hashtags) if hashtag_report else 0
    vel_score = velocity_report.velocity_score       if velocity_report   else 0
    vel_bots  = len(velocity_report.bot_velocity_actors) if velocity_report else 0
    seed_score= seeding_report.propagation_score     if seeding_report    else 0
    seed_count= seeding_report.total_seeded          if seeding_report    else 0
    corr_score= correlation_report.correlation_score if correlation_report else 0
    corr_high = sum(1 for p in (correlation_report.top_pairs or []) if p.label == "HIGH") if correlation_report else 0
    attr_score= attribution_report.attribution_score if attribution_report else 0
    attr_ops  = attribution_report.total_operators   if attribution_report else 0
    th_score  = troll_report.bot_risk_score          if troll_report       else 0
    th_conf   = len(troll_report.confirmed_bots)     if troll_report       else 0
    th_foreign= len(troll_report.foreign_names)      if troll_report       else 0
    th_pages  = len(troll_report.page_operators)     if troll_report       else 0
    eng_score = engagement_report.anomaly_score       if engagement_report  else 0
    eng_boost = len(engagement_report.bot_boosted)   if engagement_report  else 0
    eng_ghost = len(engagement_report.ghost_posts)   if engagement_report  else 0
    cont_score= contagion_report.contagion_score      if contagion_report   else 0
    cont_dir  = contagion_report.shift_direction      if contagion_report   else "NONE"
    cont_aff  = contagion_report.affected_posts       if contagion_report   else 0
    id_score  = identity_report.persistence_score       if identity_report    else 0
    id_conf   = len(identity_report.confirmed_morphs)  if identity_report    else 0
    id_uniq   = identity_report.unique_operators        if identity_report    else 0
    mut_score = mutation_report.mutation_score          if mutation_report    else 0
    mut_pivot = mutation_report.pivot_events            if mutation_report    else 0
    mut_total = len(mutation_report.mutations)          if mutation_report    else 0
    da_score  = dark_amp_report.amp_score              if dark_amp_report    else 0
    da_dark   = len(dark_amp_report.dark_amplified)   if dark_amp_report    else 0
    da_base   = dark_amp_report.baseline_velocity      if dark_amp_report    else 0
    sh_score  = shift_report.shift_score               if shift_report       else 0
    sh_conf   = shift_report.confirmed_shifts          if shift_report       else 0
    sh_rot    = shift_report.total_rotated             if shift_report       else 0
    rc_score  = reply_report.hijack_score             if reply_report       else 0
    rc_hijack = len(reply_report.hijacked_posts)      if reply_report       else 0
    rc_career = len(reply_report.career_hijackers)    if reply_report       else 0
    cc_score  = cross_campaign_report.persistence_score if cross_campaign_report else 0
    cc_pro    = len(cross_campaign_report.professional) if cross_campaign_report else 0
    cc_total  = cross_campaign_report.total_tracked     if cross_campaign_report else 0

    neg_count = sum(1 for p in posts if (p.get("label") or "").upper() in ("NEGATIVO", "AGRESIVO"))
    neg_pct   = round(neg_count / max(total, 1) * 100)

    return {
        "total_posts":      total,
        "bot_pct":          bot_pct,
        "neg_pct":          neg_pct,
        "coord_score":      coord,
        "mean_hcs":         mean_hcs,
        "operators":        op_count,
        "attack_pages":     atk_pages,
        "total_actors":     cib_result.total_actors if cib_result else 0,
        "total_edges":      cib_result.total_edges  if cib_result else 0,
        "temporal_score":   t_score,
        "attack_waves":     t_waves,
        "stylo_bots":       s_bots,
        "stylo_clusters":   s_clust,
        "sentiment_score":  sent_score,
        "seeded_posts":     fm_seeds,
        "seed_accounts":    fm_accts,
        "narrative_score":  narr_score,
        "bot_clusters":     bot_clust,
        "lifecycle_score":  lc_score,
        "sleeper_accounts": lc_sleep,
        "sleeper_cells":    lc_cells,
        "injection_score":  inj_score,
        "narratives_found":  inj_count,
        "topology_score":    top_score,
        "pagerank_gini":     top_gini,
        "hashtag_score":     ht_score,
        "weaponized_tags":   ht_weap,
        "velocity_score":    vel_score,
        "bot_velocity_actors": vel_bots,
        "seeding_score":     seed_score,
        "seeded_narratives": seed_count,
        "correlation_score": corr_score,
        "high_corr_pairs":   corr_high,
        "attribution_score": attr_score,
        "attributed_operators": attr_ops,
        "troll_score":          th_score,
        "confirmed_bots":       th_conf,
        "foreign_name_actors":  th_foreign,
        "page_operators":       th_pages,
        "engagement_score":     eng_score,
        "bot_boosted_posts":    eng_boost,
        "ghost_posts":          eng_ghost,
        "contagion_score":      cont_score,
        "contagion_direction":  cont_dir,
        "contagion_affected":   cont_aff,
        "id_score":             id_score,
        "id_confirmed_morphs":  id_conf,
        "id_unique_operators":  id_uniq,
        "mut_score":            mut_score,
        "mut_pivot":            mut_pivot,
        "mut_total":            mut_total,
        "da_score":             da_score,
        "da_dark_posts":        da_dark,
        "da_baseline":          da_base,
        "sh_score":             sh_score,
        "sh_confirmed":         sh_conf,
        "sh_rotated":           sh_rot,
        "rc_score":             rc_score,
        "rc_hijacked_posts":    rc_hijack,
        "rc_career_hijackers":  rc_career,
        "cc_score":             cc_score,
        "cc_professional":      cc_pro,
        "cc_total_tracked":     cc_total,
    }


def _build_lifecycle_data(lifecycle_report) -> dict:
    if not lifecycle_report:
        return {
            "anomaly_score": 0, "total_actors": 0,
            "sleepers": [], "bursters": [], "coordinators": [],
            "cells": [], "campaign_start": None, "summary": "",
        }
    def _actor_dict(a) -> dict:
        return {
            "actor":       a.actor,
            "first_seen":  a.first_seen.strftime("%Y-%m-%d %H:%M") if a.first_seen else None,
            "window_h":    a.active_window_hours,
            "cph":         a.comments_per_hour,
            "lag_h":       a.activation_lag_hours,
            "burst":       a.burst_count,
            "score":       a.anomaly_score,
            "label":       a.lifecycle_label,
            "flags":       a.anomaly_flags[:3],
        }
    def _cell_dict(c) -> dict:
        return {
            "cell_id":      c.cell_id,
            "actors":       c.actors[:8],
            "act_start":    c.activation_start.strftime("%Y-%m-%d %H:%M") if c.activation_start else None,
            "act_end":      c.activation_end.strftime("%Y-%m-%d %H:%M") if c.activation_end else None,
            "posts_hit":    len(c.posts_targeted),
            "coord_score":  c.coordination_score,
        }
    return {
        "anomaly_score":  lifecycle_report.anomaly_score,
        "total_actors":   lifecycle_report.total_actors,
        "sleepers":       [_actor_dict(a) for a in lifecycle_report.sleepers[:30]],
        "bursters":       [_actor_dict(a) for a in lifecycle_report.bursters[:20]],
        "coordinators":   [_actor_dict(a) for a in lifecycle_report.coordinators[:20]],
        "top_actors":     [_actor_dict(a) for a in lifecycle_report.actors[:30]],
        "cells":          [_cell_dict(c) for c in lifecycle_report.sleeper_cells[:5]],
        "campaign_start": (lifecycle_report.campaign_start.strftime("%Y-%m-%d %H:%M")
                           if lifecycle_report.campaign_start else None),
        "summary":        lifecycle_report.summary,
    }


def _build_injection_data(injection_report) -> dict:
    if not injection_report:
        return {
            "injection_score": 0, "total_narratives": 0,
            "total_attack_comments": 0, "injections": [],
            "top_injectors": [], "chains": [], "summary": "",
        }
    def _inj_dict(i) -> dict:
        return {
            "id":          i.narrative_id,
            "seed":        i.seed_account,
            "terms":       i.top_terms[:5],
            "seed_ts":     i.seed_timestamp.strftime("%Y-%m-%d %H:%M") if i.seed_timestamp else None,
            "seed_text":   i.seed_comment_text[:100],
            "prop_count":  i.propagation_count,
            "prop_posts":  i.propagation_posts,
            "co_inj":      i.co_injectors[:3],
            "score":       i.injection_score,
        }
    def _chain_dict(c) -> dict:
        return {
            "id":    c.narrative_id,
            "steps": [{"ts": s.ts, "actor": s.actor, "text": s.text_excerpt[:80]}
                      for s in c.steps[:10]],
        }
    return {
        "injection_score":       injection_report.injection_score,
        "total_narratives":      injection_report.total_narratives,
        "total_attack_comments": injection_report.total_attack_comments,
        "injections":            [_inj_dict(i) for i in injection_report.injections[:15]],
        "top_injectors":         [{"actor": a, "count": n}
                                  for a, n in injection_report.top_injectors[:10]],
        "chains":                [_chain_dict(c) for c in injection_report.propagation_chains[:5]],
        "summary":               injection_report.summary,
    }


def _build_topology_data(topology_report) -> dict:
    if not topology_report:
        return {"score": 0, "gini": 0.0, "actors": [], "command_chain": [],
                "amplifiers": [], "communities": [], "summary": ""}
    actors = [
        {
            "actor":     a.actor,
            "rank":      a.rank,
            "score":     a.influence_score,
            "pagerank":  a.pagerank,
            "betweenness": a.betweenness,
            "degree":    a.degree,
            "role":      a.role,
            "suspect":   a.is_suspect,
            "susp_score":a.suspect_score,
            "community": a.community_id,
        }
        for a in topology_report.actors[:25]
    ]
    communities = [
        {
            "id":          c.community_id,
            "size":        c.size,
            "top_actor":   c.top_actor,
            "avg_inf":     c.avg_influence,
            "susp_ratio":  c.suspect_ratio,
        }
        for c in topology_report.top_communities[:10]
    ]
    return {
        "score":        topology_report.influence_score,
        "gini":         topology_report.pagerank_gini,
        "coord_score":  topology_report.coordination_score,
        "total_actors": topology_report.total_actors,
        "actors":       actors,
        "command_chain":topology_report.command_chain[:8],
        "amplifiers":   topology_report.amplifiers[:8],
        "hubs":         topology_report.hubs[:8],
        "communities":  communities,
        "suspect_top":  round(topology_report.suspect_top_ratio * 100, 1),
        "summary":      topology_report.summary,
    }


def _build_hashtag_data(hashtag_report) -> dict:
    if not hashtag_report:
        return {"score": 0, "total": 0, "weaponized": [], "organic": [],
                "profiles": [], "top_seeders": [], "summary": ""}
    profiles = [
        {
            "tag":        p.hashtag,
            "uses":       p.total_uses,
            "actors":     p.unique_actors,
            "posts":      p.posts_hit,
            "first":      p.first_actor,
            "first_ts":   p.first_seen.strftime("%Y-%m-%d %H:%M") if p.first_seen else None,
            "peak":       p.peak_hour_count,
            "rate":       p.adoption_rate,
            "weaponized": p.weaponized,
            "label":      p.weaponization_label,
            "seeders":    p.seeder_accounts[:5],
            "curve":      p.adoption_curve[:12],
        }
        for p in hashtag_report.hashtag_profiles[:30]
    ]
    return {
        "score":          hashtag_report.weaponization_score,
        "total":          hashtag_report.total_hashtags,
        "weaponized":     hashtag_report.weaponized_hashtags[:20],
        "organic":        hashtag_report.organic_hashtags[:10],
        "profiles":       profiles,
        "top_seeders":    hashtag_report.top_seeders[:15],
        "summary":        hashtag_report.summary,
    }


def _build_velocity_data(velocity_report) -> dict:
    if not velocity_report:
        return {
            "score": 0, "total": 0, "mean_cph": 0, "max_cph": 0,
            "bot_velocity": [], "suspicious": [], "actors": [], "summary": "",
        }
    return {
        "score":        velocity_report.velocity_score,
        "total":        velocity_report.total_actors,
        "mean_cph":     velocity_report.mean_cph,
        "max_cph":      velocity_report.max_cph,
        "bot_velocity": velocity_report.bot_velocity_actors[:15],
        "suspicious":   velocity_report.suspicious_actors[:10],
        "actors":       [
            {
                "actor":   p.actor,
                "cph":     p.cph,
                "comments":p.total_comments,
                "posts":   p.unique_posts,
                "span_h":  p.span_hours,
                "label":   p.velocity_label,
                "score":   p.velocity_score,
            }
            for p in velocity_report.profiles[:25]
        ],
        "summary":      velocity_report.summary,
    }


def _build_seeding_data(seeding_report) -> dict:
    if not seeding_report:
        return {
            "score": 0, "total": 0,
            "cross_actors": [], "seeds": [], "summary": "",
        }
    return {
        "score":       seeding_report.propagation_score,
        "total":       seeding_report.total_seeded,
        "cross_actors": seeding_report.cross_post_actors[:15],
        "seeds":       [
            {
                "key":       s.key[:55],
                "text":      s.full_text[:120],
                "first":     s.first_actor,
                "first_url": s.first_post_url,
                "first_ts":  s.first_seen.strftime("%Y-%m-%d %H:%M") if s.first_seen else None,
                "posts":     s.unique_posts,
                "actors":    s.unique_actors,
                "spread":    s.propagation_count,
            }
            for s in seeding_report.seeds[:15]
        ],
        "summary":     seeding_report.summary,
    }


def _build_correlation_data(correlation_report) -> dict:
    if not correlation_report:
        return {
            "score": 0, "total_pairs": 0, "max_j": 0, "mean_j": 0,
            "high_posts": [], "pairs": [], "summary": "",
        }
    return {
        "score":       correlation_report.correlation_score,
        "total_pairs": correlation_report.total_pairs,
        "max_j":       correlation_report.max_jaccard,
        "mean_j":      correlation_report.mean_jaccard,
        "high_posts":  correlation_report.highly_correlated_posts[:10],
        "pairs":       [
            {
                "a":       p.post_a,
                "b":       p.post_b,
                "shared":  p.shared_actors,
                "a_size":  p.actors_a,
                "b_size":  p.actors_b,
                "jaccard": p.jaccard,
                "label":   p.label,
            }
            for p in correlation_report.top_pairs[:15]
        ],
        "summary":     correlation_report.summary,
    }


def _build_attribution_data(attribution_report) -> dict:
    if not attribution_report:
        return {
            "score": 0, "total_bots": 0, "total_operators": 0,
            "edges": 0, "operators": [], "summary": "",
        }
    return {
        "score":      attribution_report.attribution_score,
        "total_bots": attribution_report.total_bots,
        "total_ops":  attribution_report.total_operators,
        "edges":      attribution_report.bipartite_edges,
        "operators":  [
            {
                "operator":  o.operator,
                "label":     o.operation_label,
                "bots":      o.attributed_bots[:8],
                "co_posts":  o.unique_co_posts,
                "excl":      o.bot_exclusivity,
                "conf":      o.confidence,
            }
            for o in attribution_report.operators[:12]
        ],
        "summary":    attribution_report.summary,
    }


def _build_troll_data(troll_report) -> dict:
    if not troll_report:
        return {
            "score": 0, "total": 0, "confirmed": [], "high_risk": [],
            "suspicious": [], "foreign_names": [], "page_operators": [],
            "multi_page_ops": [], "profiles": [], "summary": "",
        }
    sev_ord = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    return {
        "score":         troll_report.bot_risk_score,
        "total":         troll_report.total_analyzed,
        "confirmed":     troll_report.confirmed_bots[:20],
        "high_risk":     troll_report.high_risk[:20],
        "suspicious":    troll_report.suspicious[:20],
        "foreign_names": troll_report.foreign_names[:20],
        "page_operators":troll_report.page_operators[:15],
        "multi_page_ops":troll_report.multi_page_ops[:10],
        "profiles":      [
            {
                "actor":   p.actor,
                "score":   p.bot_risk_score,
                "class":   p.classification,
                "cph":     p.cph,
                "posts":   p.posts_attacked,
                "attacks": p.attack_ratio,
                "comments":p.total_comments,
                "sample":  p.comment_sample[:2],
                "signals": [
                    {
                        "code":     s.code,
                        "label":    s.label,
                        "severity": s.severity,
                        "detail":   s.detail[:200],
                        "value":    round(s.value, 3),
                    }
                    for s in sorted(p.signals, key=lambda x: sev_ord.get(x.severity, 4))[:5]
                ],
            }
            for p in troll_report.profiles[:30]
        ],
        "summary":       troll_report.summary,
    }


def _build_identity_data(identity_report) -> dict:
    if not identity_report:
        return {"score":0,"total":0,"unique":0,"confirmed":[],"probable":[],"morphs":[],"summary":""}
    return {
        "score":     identity_report.persistence_score,
        "total":     identity_report.total_fingerprinted,
        "unique":    identity_report.unique_operators,
        "confirmed": identity_report.confirmed_morphs[:10],
        "probable":  identity_report.probable_morphs[:10],
        "morphs":    [
            {
                "actor_a":  m.actor_a,
                "actor_b":  m.actor_b,
                "camp_a":   m.campaign_a,
                "camp_b":   m.campaign_b,
                "sim":      m.similarity,
                "conf":     m.confidence,
                "fp_a":     m.fingerprint_a,
                "fp_b":     m.fingerprint_b,
                "evidence": m.evidence[:300],
            }
            for m in identity_report.morphs[:20]
        ],
        "summary": identity_report.summary,
    }


def _build_mutation_data(mutation_report) -> dict:
    if not mutation_report:
        return {"score":0,"mutations":[],"seed":[],"final":[],"pivot":0,"exp":0,"inj":0,"mutator":None,"summary":""}
    return {
        "score":   mutation_report.mutation_score,
        "pivot":   mutation_report.pivot_events,
        "exp":     mutation_report.expansion_events,
        "inj":     mutation_report.injection_events,
        "mutator": mutation_report.most_active_mutator,
        "seed":    mutation_report.seed_narrative[:8],
        "final":   mutation_report.final_narrative[:8],
        "mutations":[
            {
                "id":       m.mutation_id,
                "type":     m.mutation_type,
                "drop":     m.similarity_drop,
                "from_ts":  m.from_snapshot.start_ts[:16],
                "to_ts":    m.to_snapshot.start_ts[:16],
                "new":      m.new_terms[:6],
                "dropped":  m.dropped_terms[:4],
                "intro":    m.mutation_introducer,
                "adoption": m.adoption_count,
                "score":    m.mutation_score,
                "from_terms": m.from_snapshot.top_terms[:6],
                "to_terms":   m.to_snapshot.top_terms[:6],
            }
            for m in mutation_report.mutations[:10]
        ],
        "snapshots":[
            {"id":s.window_id,"start":s.start_ts[:16],"terms":s.top_terms[:5],"intensity":s.intensity,"n":s.comment_count}
            for s in mutation_report.snapshots[:30]
        ],
        "summary": mutation_report.summary,
    }


def _build_dark_amp_data(dark_amp_report) -> dict:
    if not dark_amp_report:
        return {"score":0,"baseline":0,"total":0,"dark":[],"suspicious":[],"events":[],"summary":""}
    return {
        "score":      dark_amp_report.amp_score,
        "baseline":   dark_amp_report.baseline_velocity,
        "total":      dark_amp_report.total_analyzed,
        "dark":       dark_amp_report.dark_amplified[:10],
        "suspicious": dark_amp_report.suspicious[:10],
        "events":     [
            {
                "url":    e.url,
                "source": e.source,
                "preview":e.text_preview,
                "age":    e.age_hours,
                "eng":    e.engagement_total,
                "vel":    e.velocity,
                "factor": e.amplification_factor,
                "purity": e.reaction_purity,
                "burst":  e.comment_burst_ratio,
                "class":  e.classification,
                "score":  e.amp_score,
            }
            for e in dark_amp_report.events[:20]
        ],
        "summary":    dark_amp_report.summary,
    }


def _build_shift_data(shift_report) -> dict:
    if not shift_report:
        return {"score":0,"cohorts":[],"shifts":[],"confirmed":0,"rotated":0,"summary":""}
    return {
        "score":     shift_report.shift_score,
        "confirmed": shift_report.confirmed_shifts,
        "rotated":   shift_report.total_rotated,
        "start":     shift_report.timeline_start,
        "end":       shift_report.timeline_end,
        "cohorts":   [
            {
                "id":      c.cohort_id,
                "start":   c.window_start[:16],
                "end":     c.window_end[:16],
                "actors":  len(c.actors),
                "bots":    len(c.bot_actors),
                "pct":     round(c.bot_pct, 2),
                "comments":c.comment_count,
                "patterns":c.naming_patterns,
            }
            for c in shift_report.cohorts[:24]
        ],
        "shifts":    [
            {
                "from":     s.from_cohort.window_end[:16],
                "to":       s.to_cohort.window_start[:16],
                "jaccard":  s.jaccard_overlap,
                "turnover": s.turnover_pct,
                "sim":      s.naming_sim,
                "conf":     s.confidence,
                "score":    s.shift_score,
                "from_patterns": s.from_cohort.naming_patterns,
                "to_patterns":   s.to_cohort.naming_patterns,
            }
            for s in shift_report.shift_events[:10]
        ],
        "summary":   shift_report.summary,
    }


def _build_reply_data(reply_report) -> dict:
    if not reply_report:
        return {"score": 0, "hijacked": [], "targeted": 0, "career": [], "posts": [], "summary": ""}
    return {
        "score":    reply_report.hijack_score,
        "hijacked": reply_report.hijacked_posts[:10],
        "targeted": reply_report.total_targeted,
        "career":   reply_report.career_hijackers[:15],
        "posts":    [
            {
                "url":     p.url,
                "source":  p.source,
                "score":   p.hijack_score,
                "organic": p.organic_count,
                "bots":    p.bot_reply_count,
                "sat":     round(p.saturation_ratio, 2),
                "type":    p.dominant_attack,
                "targets": [
                    {
                        "author":  t.organic_author,
                        "text":    t.organic_text[:80],
                        "likes":   t.organic_likes,
                        "bots":    t.bot_attackers[:5],
                        "count":   t.reply_count,
                        "delta":   t.attack_delta_s,
                        "type":    t.attack_type,
                        "score":   t.intensity_score,
                    }
                    for t in p.targeted_comments[:4]
                ],
            }
            for p in reply_report.posts[:15]
        ],
        "summary": reply_report.summary,
    }


def _build_cross_campaign_data(cc_report) -> dict:
    if not cc_report:
        return {"score": 0, "total": 0, "campaigns": 0, "pro": [], "per": [], "actors": [], "summary": ""}
    return {
        "score":     cc_report.persistence_score,
        "total":     cc_report.total_tracked,
        "campaigns": cc_report.campaigns_count,
        "new":       cc_report.new_discoveries,
        "pro":       cc_report.professional[:10],
        "per":       cc_report.persistent[:10],
        "recurring": cc_report.recurring[:10],
        "actors":    [
            {
                "name":      a.name,
                "class":     a.classification,
                "camps":     a.campaign_count,
                "campaigns": a.campaigns[:5],
                "avg_score": a.avg_bot_score,
                "total_c":   a.total_comments,
                "score":     a.persistence_score,
                "signals":   a.signals_summary,
                "last_seen": a.last_seen,
            }
            for a in cc_report.actors[:30]
        ],
        "summary": cc_report.summary,
    }


def _build_engagement_data(engagement_report) -> dict:
    if not engagement_report:
        return {
            "score": 0, "baseline": 0, "total": 0,
            "bot_boosted": [], "suspicious": [], "ghost": [], "posts": [], "summary": "",
        }
    return {
        "score":       engagement_report.anomaly_score,
        "baseline":    engagement_report.baseline_ratio,
        "total":       engagement_report.total_analyzed,
        "bot_boosted": engagement_report.bot_boosted[:10],
        "suspicious":  engagement_report.suspicious[:10],
        "ghost":       engagement_report.ghost_posts[:10],
        "posts":       [
            {
                "url":     p.url,
                "source":  p.source,
                "preview": p.text_preview,
                "r":       p.reactions,
                "c":       p.comments,
                "s":       p.shares,
                "ratio":   p.ratio,
                "dev":     p.deviation_pct,
                "class":   p.classification,
                "score":   p.anomaly_score,
            }
            for p in engagement_report.posts[:20]
        ],
        "summary":     engagement_report.summary,
    }


def _build_contagion_data(contagion_report) -> dict:
    if not contagion_report:
        return {
            "score": 0, "arrival": None, "direction": "NONE",
            "affected": 0, "pre": {}, "during": {}, "post": {}, "posts": [], "summary": "",
        }

    def _w(w) -> dict | None:
        if not w:
            return None
        return {
            "label":    w.label,
            "n":        w.comment_count,
            "neg":      w.neg_avg,
            "agg":      w.agg_avg,
            "pos":      w.pos_avg,
            "dominant": w.dominant,
        }

    return {
        "score":     contagion_report.contagion_score,
        "arrival":   contagion_report.bot_arrival_ts,
        "direction": contagion_report.shift_direction,
        "affected":  contagion_report.affected_posts,
        "pre":       contagion_report.pre_bot_sentiment,
        "during":    contagion_report.during_bot_sentiment,
        "post":      contagion_report.post_bot_sentiment,
        "posts":     [
            {
                "url":       p.url,
                "source":    p.source,
                "preview":   p.text_preview,
                "shift":     p.shift_magnitude,
                "confirmed": p.contagion_confirmed,
                "peak_agg":  p.peak_agg_comment,
                "pre":       _w(p.pre_bot),
                "during":    _w(p.during_bot),
                "post":      _w(p.post_bot),
            }
            for p in contagion_report.posts[:10]
        ],
        "summary":   contagion_report.summary,
    }


def _build_hcs_data(hcs_report) -> dict:
    if not hcs_report:
        return {"labels": [], "counts": [], "colors": []}
    labels = ["CONFIRMED BOT", "HIGH RISK", "SUSPICIOUS", "LIKELY HUMAN", "HUMAN"]
    counts = [
        len(hcs_report.confirmed_bots),
        len(hcs_report.high_risk),
        len(hcs_report.suspicious),
        len(hcs_report.likely_human),
        len(hcs_report.human),
    ]
    colors = ["#f38ba8", "#fab387", "#f9e2af", "#89b4fa", "#a6e3a1"]
    return {"labels": labels, "counts": counts, "colors": colors}


def _build_timeline_data(posts: list[dict]) -> dict:
    by_date: dict[str, dict] = {}
    for p in posts:
        d = (p.get("date") or "")[:10]
        if not d:
            continue
        if d not in by_date:
            by_date[d] = {"negative": 0, "positive": 0, "neutral": 0}
        lbl = (p.get("label") or "").upper()
        if lbl in ("NEGATIVO", "AGRESIVO"):
            by_date[d]["negative"] += 1
        elif lbl == "POSITIVO":
            by_date[d]["positive"] += 1
        else:
            by_date[d]["neutral"] += 1

    dates = sorted(by_date.keys())
    return {
        "dates":    dates,
        "negative": [by_date[d]["negative"] for d in dates],
        "positive": [by_date[d]["positive"] for d in dates],
        "neutral":  [by_date[d]["neutral"]  for d in dates],
    }


def _build_suspects_data(comment_report, hcs_report) -> list[dict]:
    rows: list[dict] = []
    hcs_map = {}
    if hcs_report:
        hcs_map = {s.actor: s for s in hcs_report.actor_scores}

    suspects = comment_report.top_bot_suspects if comment_report else []
    for s in suspects[:200]:
        hcs_obj = hcs_map.get(s.author)
        rows.append({
            "author":       s.author,
            "score":        s.composite_score,
            "attacks":      s.total_attacks,
            "posts":        s.posts_attacked,
            "cross_media":  s.cross_media,
            "hcs":          hcs_obj.hcs    if hcs_obj else 50,
            "hcs_label":    hcs_obj.label  if hcs_obj else "?",
            "signals":      s.signals[:3],
            "sample":       s.sample_attacks[0][:60] if s.sample_attacks else "",
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


def _build_ownership_data(ownership_report) -> dict:
    if not ownership_report:
        return {"operators": [], "attack_pages": [], "bot_bindings": []}

    operators = [
        {
            "id":         op.operator_id,
            "pages":      op.controlled_pages,
            "bots":       op.bot_army[:10],
            "confidence": op.confidence,
            "label":      op.confidence_label,
            "attacks":    op.attack_volume,
            "signals":    op.signals,
        }
        for op in ownership_report.operator_profiles[:20]
    ]
    bindings = [
        {
            "bot":       b.bot_actor,
            "pages":     b.bound_pages[:5],
            "score":     b.binding_score,
            "operator":  b.likely_operator,
        }
        for b in ownership_report.bot_bindings[:50]
    ]
    return {
        "summary":      ownership_report.network_summary,
        "operators":    operators,
        "attack_pages": ownership_report.attack_pages[:30],
        "bot_bindings": bindings,
    }


def _build_temporal_data(temporal_report) -> dict:
    if not temporal_report:
        return {"score": 0, "waves": [], "sync_pairs": [], "timeline": [], "suspicious_actors": [], "summary": ""}

    waves = [
        {
            "id":           w.wave_id,
            "start":        w.start.isoformat(),
            "end":          w.end.isoformat(),
            "duration_s":   w.duration_s,
            "participants": w.participants,
            "event_count":  len(w.events),
            "intensity":    w.intensity,
            "peak_density": w.peak_density,
        }
        for w in temporal_report.waves[:30]
    ]
    pairs = [
        {
            "author_a": p.author_a,
            "author_b": p.author_b,
            "delta_s":  p.delta_s,
            "post_url": p.post_url,
        }
        for p in temporal_report.sync_pairs[:20]
    ]
    return {
        "score":            temporal_report.overall_score,
        "waves":            waves,
        "sync_pairs":       pairs,
        "timeline":         temporal_report.attack_timeline[:72],  # max 3 days hourly
        "suspicious_actors":temporal_report.suspicious_actors[:20],
        "summary":          temporal_report.summary,
    }


def _build_stylo_data(stylo_report) -> dict:
    if not stylo_report:
        return {"clusters": [], "clone_pairs": [], "copy_paste": [], "bot_actors": [], "summary": ""}

    clusters = [
        {
            "id":         cl.cluster_id,
            "label":      cl.label,
            "actors":     cl.actors[:10],
            "similarity": cl.similarity,
        }
        for cl in stylo_report.clusters[:20]
    ]
    clone_pairs = [
        {"actor_a": a, "actor_b": b, "sim": sim}
        for a, b, sim in stylo_report.clone_pairs[:15]
    ]
    copy_paste = [
        {"sig": g.signature, "count": g.count, "actors": g.actors[:8]}
        for g in stylo_report.copy_paste_groups[:10]
    ]
    return {
        "clusters":   clusters,
        "clone_pairs":clone_pairs,
        "copy_paste": copy_paste,
        "bot_actors": stylo_report.bot_style_actors[:30],
        "summary":    stylo_report.summary,
    }


def _build_sentiment_data(sentiment_report) -> dict:
    if not sentiment_report:
        return {"score": 0, "seeded": [], "reversed": [], "seed_accounts": [], "summary": ""}

    seeded = [
        {
            "url":     d.post_url[:80],
            "label":   d.manipulation_label,
            "delta":   round(d.manipulation_delta, 4),
            "actors":  d.dominant_neg_actors[:6],
            "windows": [
                {"label": w.label, "total": w.total,
                 "neg": w.negative, "pos": w.positive,
                 "neg_ratio": round(w.neg_ratio, 3)}
                for w in d.windows
            ],
        }
        for d in sentiment_report.post_deltas
        if d.manipulation_label in ("SEEDED", "REVERSED")
    ][:30]

    return {
        "score":         sentiment_report.manipulation_score,
        "seeded":        seeded,
        "seeded_count":  len(sentiment_report.seeded_posts),
        "reversed_count":len(sentiment_report.reversed_posts),
        "seed_accounts": sentiment_report.top_seed_accounts[:20],
        "summary":       sentiment_report.summary,
    }


def _build_first_mover_data(first_mover_report) -> dict:
    if not first_mover_report:
        return {"score": 0, "seed_accounts": [], "teams": [], "summary": ""}

    accounts = [
        {
            "actor":     p.actor,
            "count":     p.seed_count,
            "avg_pos":   round(p.avg_position, 2),
            "posts":     len(p.posts),
            "sample":    p.sample_texts[0][:60] if p.sample_texts else "",
        }
        for p in first_mover_report.seed_accounts[:30]
    ]
    teams = [
        {
            "id":     t.team_id,
            "actors": t.actors[:8],
            "posts":  len(t.posts),
        }
        for t in first_mover_report.seeding_teams[:10]
    ]
    return {
        "score":         first_mover_report.overall_score,
        "seed_accounts": accounts,
        "teams":         teams,
        "top_actors":    first_mover_report.top_seed_actors[:15],
        "summary":       first_mover_report.summary,
    }


def _build_semantic_data(semantic_report) -> dict:
    if not semantic_report:
        return {"score": 0, "clusters": [], "amplifiers": [], "soldiers": [], "summary": ""}

    clusters = [
        {
            "id":         cl.cluster_id,
            "label":      cl.label,
            "size":       cl.size,
            "bot_ratio":  cl.bot_ratio,
            "top_terms":  cl.top_terms[:6],
            "actors":     cl.actors[:8],
            "sample":     cl.sample_texts[0][:60] if cl.sample_texts else "",
            "centroid_sim": cl.centroid_sim,
        }
        for cl in semantic_report.clusters[:20]
    ]
    return {
        "score":       semantic_report.narrative_score,
        "clusters":    clusters,
        "bot_dom":     semantic_report.bot_dominated_count,
        "amplifiers":  semantic_report.amplifiers[:20],
        "soldiers":    semantic_report.soldiers[:20],
        "total_comments": semantic_report.total_comments,
        "clustered":   semantic_report.clustered_comments,
        "threshold":   semantic_report.threshold_used,
        "summary":     semantic_report.summary,
    }


def _build_legal_data(legal_report) -> dict:
    if not legal_report:
        return {"case_id": "", "total_items": 0, "categories": {}, "manifest_hash": "", "summary": ""}

    mf = legal_report.manifest
    return {
        "case_id":       mf.case_id,
        "generated_at":  mf.generated_at,
        "total_items":   mf.total_items,
        "categories":    mf.categories,
        "manifest_hash": mf.manifest_hash,
        "html_path":     legal_report.html_path or "",
        "json_path":     legal_report.json_path or "",
        "summary":       legal_report.summary,
    }


# ── New data builders ─────────────────────────────────────────────────────────

def _build_cib_score_data(r) -> dict:
    if not r:
        return {
            "score": 0, "label": "ORGANIC", "engines_present": 0,
            "engines_active": 0, "data_quality": "INSUFFICIENT",
            "dimensions": [], "top_signals": [],
            "narrative": "Insufficient comment data. Run with --comments-on-top to enable CIB analysis.",
        }
    return {
        "score":           getattr(r, "overall_score", 0),
        "label":           getattr(r, "confidence_label", "ORGANIC"),
        "engines_present": getattr(r, "engines_present", 0),
        "engines_active":  getattr(r, "engines_active",  0),
        "engines_missing": getattr(r, "engines_missing", []),
        "data_quality":    getattr(r, "data_quality",    "INSUFFICIENT"),
        "top_signals":     getattr(r, "top_signals",     []),
        "narrative":       getattr(r, "narrative",       ""),
        "dimensions": [
            {
                "engine":       d.engine,
                "label":        d.label,
                "score":        d.score,
                "weight":       d.weight,
                "contribution": d.contribution,
            }
            for d in getattr(r, "dimensions", [])
        ],
    }


def _build_chain_data(r) -> list:
    if not r:
        return []
    chains = []
    for ch in getattr(r, "chains", []):
        chains.append({
            "actor":             ch.actor,
            "score":             ch.bot_risk_score,
            "classification":    ch.classification,
            "classification_es": ch.classification_es,
            "total_signals":     ch.total_signals,
            "summary":           ch.summary_sentence,
            "signals": [
                {
                    "code":         s.code,
                    "source":       s.source_engine,
                    "severity":     s.severity,
                    "title":        s.title,
                    "explanation":  s.explanation,
                    "evidence":     s.evidence,
                    "points":       s.points,
                }
                for s in ch.signals
            ],
        })
    return chains


def _build_multi_source_data(r) -> dict:
    if not r:
        return {"sources": [], "score": 0, "cross_actors": [],
                "page_pairs": [], "sync_terms": [], "summary": ""}
    return {
        "sources":         getattr(r, "sources", []),
        "score":           getattr(r, "cross_page_score", 0),
        "total_actors":    getattr(r, "total_actors", 0),
        "confirmed_cross": getattr(r, "confirmed_cross_bots", []),
        "sync_terms":      getattr(r, "narrative_sync_terms", []),
        "summary":         getattr(r, "summary", ""),
        "cross_actors": [
            {
                "name":       a.name,
                "pages":      a.pages_active,
                "page_count": a.page_count,
                "bot_score":  a.bot_score,
                "is_bot":     a.is_confirmed_bot,
                "risk":       a.cross_page_risk,
            }
            for a in getattr(r, "cross_page_actors", [])[:30]
        ],
        "page_pairs": [
            {
                "page_a":   p.page_a,
                "page_b":   p.page_b,
                "shared":   p.overlap_count,
                "jaccard":  p.overlap_pct,
                "label":    p.coord_label,
                "actors":   p.shared_actors[:8],
            }
            for p in getattr(r, "page_pairs", [])[:10]
        ],
    }


def _build_glossary_data(cfg: dict | None) -> dict:
    from engines.docx_reporter import _DEFAULT_GLOSSARY_ABBR, _DEFAULT_GLOSSARY_TERMS
    c = (cfg or {}).get("glossary", {})
    abbr  = {**_DEFAULT_GLOSSARY_ABBR,  **c.get("abbreviations", {})}
    terms = {**_DEFAULT_GLOSSARY_TERMS, **c.get("terms", {})}
    return {
        "abbreviations": [{"key": k, "def": v} for k, v in abbr.items()],
        "terms":         [{"term": k, "def": v} for k, v in terms.items()],
    }


# ── HTML template ─────────────────────────────────────────────────────────────

def _build_html(target: str, date_lbl: str, data_json: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FBSCRAP · {target}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root {{
    --bg:      #1e1e2e; --surface: #181825; --surface2: #313244;
    --overlay: #45475a; --text:    #cdd6f4; --subtext:  #a6adc8;
    --red:     #f38ba8; --orange:  #fab387; --yellow:   #f9e2af;
    --green:   #a6e3a1; --blue:    #89b4fa; --purple:   #cba6f7;
    --cyan:    #89dceb; --pink:    #f5c2e7;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'Consolas', monospace; font-size: 13px; }}
  header {{ background: var(--surface); border-bottom: 2px solid var(--red); padding: 18px 24px; display: flex; justify-content: space-between; align-items: center; }}
  header h1 {{ color: var(--red); font-size: 18px; letter-spacing: 2px; }}
  header .meta {{ color: var(--subtext); font-size: 11px; text-align: right; }}
  .container {{ max-width: 1600px; margin: 0 auto; padding: 20px; }}
  .section {{ margin-bottom: 32px; }}
  .section-title {{ color: var(--purple); font-size: 13px; font-weight: bold; letter-spacing: 1px; border-bottom: 1px solid var(--overlay); padding-bottom: 6px; margin-bottom: 14px; text-transform: uppercase; }}

  /* Metrics grid */
  .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 12px; }}
  .metric-card {{ background: var(--surface); border: 1px solid var(--overlay); border-radius: 8px; padding: 14px; text-align: center; }}
  .metric-card .value {{ font-size: 28px; font-weight: bold; }}
  .metric-card .label {{ color: var(--subtext); font-size: 10px; margin-top: 4px; letter-spacing: 1px; }}
  .red {{ color: var(--red); }} .orange {{ color: var(--orange); }} .yellow {{ color: var(--yellow); }}
  .green {{ color: var(--green); }} .blue {{ color: var(--blue); }} .purple {{ color: var(--purple); }}
  .cyan {{ color: var(--cyan); }}

  /* Charts row */
  .charts-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  .chart-box {{ background: var(--surface); border: 1px solid var(--overlay); border-radius: 8px; padding: 16px; }}
  .chart-box h3 {{ color: var(--cyan); font-size: 11px; margin-bottom: 10px; letter-spacing: 1px; }}
  canvas {{ max-height: 220px; }}

  /* CIB Network */
  #cib-network {{ background: var(--surface); border: 1px solid var(--overlay); border-radius: 8px; width: 100%; height: 480px; position: relative; overflow: hidden; }}
  #cib-network svg {{ width: 100%; height: 100%; }}
  .node-label {{ font-size: 9px; fill: var(--text); pointer-events: none; }}
  .tooltip {{ position: absolute; background: var(--surface2); border: 1px solid var(--overlay); border-radius: 6px; padding: 10px; font-size: 11px; pointer-events: none; opacity: 0; transition: opacity 0.2s; max-width: 260px; z-index: 100; }}

  /* Legend */
  .legend {{ display: flex; gap: 16px; flex-wrap: wrap; margin-top: 10px; }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; font-size: 10px; color: var(--subtext); }}
  .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; }}

  /* Bot suspects table */
  .search-box {{ background: var(--surface2); border: 1px solid var(--overlay); color: var(--text); padding: 8px 12px; border-radius: 6px; width: 280px; font-size: 12px; margin-bottom: 12px; }}
  .search-box::placeholder {{ color: var(--subtext); }}
  table {{ width: 100%; border-collapse: collapse; background: var(--surface); border-radius: 8px; overflow: hidden; }}
  thead tr {{ background: var(--surface2); }}
  th {{ padding: 10px 12px; text-align: left; color: var(--purple); font-size: 10px; letter-spacing: 1px; cursor: pointer; user-select: none; white-space: nowrap; }}
  th:hover {{ color: var(--cyan); }}
  td {{ padding: 8px 12px; border-bottom: 1px solid var(--overlay); font-size: 11px; }}
  tr:hover td {{ background: var(--surface2); }}
  .badge {{ display: inline-block; padding: 2px 7px; border-radius: 10px; font-size: 9px; font-weight: bold; }}
  .badge-red    {{ background: #3d1520; color: var(--red); }}
  .badge-orange {{ background: #3d2010; color: var(--orange); }}
  .badge-yellow {{ background: #3d3010; color: var(--yellow); }}
  .badge-blue   {{ background: #10203d; color: var(--blue); }}
  .badge-green  {{ background: #103d20; color: var(--green); }}
  .badge-cross  {{ background: #3d1040; color: var(--pink); }}
  .score-bar {{ display: inline-block; height: 8px; border-radius: 4px; margin-left: 6px; vertical-align: middle; }}

  /* Ownership */
  .op-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }}
  .op-card {{ background: var(--surface); border: 1px solid var(--overlay); border-radius: 8px; padding: 14px; }}
  .op-card h4 {{ color: var(--orange); font-size: 12px; margin-bottom: 8px; }}
  .op-card .conf-bar {{ height: 6px; border-radius: 3px; background: var(--overlay); margin: 6px 0; }}
  .op-card .conf-fill {{ height: 100%; border-radius: 3px; }}
  .op-detail {{ color: var(--subtext); font-size: 10px; margin-top: 4px; }}
  .tag {{ display: inline-block; background: var(--surface2); color: var(--subtext); border-radius: 4px; padding: 1px 6px; font-size: 9px; margin: 1px; }}
  .filter-btn {{ background: var(--surface); border: 1px solid var(--overlay); color: var(--subtext); border-radius: 6px; padding: 4px 10px; font-size: 10px; cursor: pointer; font-family: inherit; }}
  .filter-btn:hover, .filter-btn.active {{ border-color: var(--blue); color: var(--text); background: var(--surface2); }}
  .troll-evidence {{ background: var(--base); border-left: 2px solid var(--overlay); padding: 6px 10px; margin-top: 6px; font-size: 9px; color: var(--subtext); white-space: pre-wrap; }}

  /* Attack pages */
  .atk-page-list {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .atk-page {{ background: #3d1520; color: var(--red); border: 1px solid #6d2535; border-radius: 6px; padding: 5px 10px; font-size: 11px; }}

  /* Scrollable sections */
  .scroll-x {{ overflow-x: auto; }}
  #suspects-tbody tr.hidden {{ display: none; }}

  /* ── CIB HERO SCORE ───────────────────────────────────────────────────── */
  .cib-hero {{
    background: linear-gradient(135deg, #181825 0%, #1e1e2e 50%, #181825 100%);
    border: 2px solid var(--overlay); border-radius: 16px;
    padding: 32px 24px; margin-bottom: 28px;
    display: grid; grid-template-columns: auto 1fr auto; gap: 32px; align-items: center;
  }}
  .cib-gauge-wrap {{ display: flex; flex-direction: column; align-items: center; gap: 8px; }}
  .cib-gauge {{ position: relative; width: 160px; height: 160px; }}
  .cib-gauge svg {{ transform: rotate(-90deg); }}
  .cib-gauge-val {{
    position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%);
    text-align: center;
  }}
  .cib-gauge-val .score {{ font-size: 42px; font-weight: bold; line-height: 1; }}
  .cib-gauge-val .max   {{ font-size: 14px; color: var(--subtext); }}
  .cib-label {{ font-size: 13px; font-weight: bold; letter-spacing: 2px; text-align: center; padding: 4px 14px; border-radius: 20px; }}
  .cib-center {{ flex: 1; }}
  .cib-narrative {{ color: var(--subtext); font-size: 12px; line-height: 1.7; margin-bottom: 16px; font-style: italic; }}
  .cib-signals {{ display: flex; flex-direction: column; gap: 6px; }}
  .cib-signal-item {{
    background: var(--surface); border-left: 3px solid var(--overlay);
    border-radius: 0 6px 6px 0; padding: 8px 12px; font-size: 11px; color: var(--text);
  }}
  .cib-signal-item .sig-bullet {{ font-size: 9px; color: var(--subtext); }}
  .cib-dims {{ display: flex; flex-direction: column; gap: 5px; min-width: 200px; }}
  .cib-dim-row {{ display: flex; align-items: center; gap: 8px; font-size: 10px; }}
  .cib-dim-bar-bg {{ flex: 1; height: 6px; background: var(--overlay); border-radius: 3px; }}
  .cib-dim-bar    {{ height: 100%; border-radius: 3px; transition: width 0.8s ease; }}
  .cib-dim-label  {{ color: var(--subtext); min-width: 110px; text-align: right; font-size: 9px; }}
  .cib-dim-val    {{ color: var(--text); min-width: 32px; text-align: right; font-size: 9px; }}

  /* ── MULTI-SOURCE MATRIX ──────────────────────────────────────────────── */
  .ms-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }}
  .ms-score-pill {{
    background: var(--surface); border: 1px solid var(--overlay);
    border-radius: 20px; padding: 6px 16px; font-size: 12px; font-weight: bold;
  }}
  .ms-pair-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px,1fr)); gap: 12px; margin-bottom: 16px; }}
  .ms-pair-card {{
    background: var(--surface); border: 1px solid var(--overlay);
    border-radius: 8px; padding: 14px;
  }}
  .ms-pair-card h4 {{ font-size: 11px; color: var(--cyan); margin-bottom: 8px; }}
  .ms-overlap-bar {{ height: 8px; background: var(--overlay); border-radius: 4px; margin: 6px 0; }}
  .ms-overlap-fill {{ height: 100%; border-radius: 4px; transition: width 0.8s; }}
  .ms-actor-tags {{ display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; }}
  .ms-sync-terms {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }}
  .ms-term {{ background: #2a1a3a; color: var(--purple); border: 1px solid #4a2a5a; border-radius: 4px; padding: 3px 8px; font-size: 10px; }}

  /* ── CONFIDENCE CHAIN CARDS ───────────────────────────────────────────── */
  .chain-search {{ background: var(--surface2); border: 1px solid var(--overlay); color: var(--text); padding: 8px 12px; border-radius: 6px; width: 320px; font-size: 12px; margin-bottom: 16px; font-family: inherit; }}
  .chain-search::placeholder {{ color: var(--subtext); }}
  .chain-filters {{ display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }}
  .chain-cards {{ display: flex; flex-direction: column; gap: 12px; }}
  .chain-card {{
    background: var(--surface); border: 1px solid var(--overlay); border-radius: 10px;
    overflow: hidden; transition: border-color 0.2s;
  }}
  .chain-card:hover {{ border-color: var(--blue); }}
  .chain-card-header {{
    display: flex; align-items: center; gap: 12px; padding: 14px 16px;
    cursor: pointer; user-select: none;
  }}
  .chain-card-header:hover {{ background: var(--surface2); }}
  .chain-score-circle {{
    width: 44px; height: 44px; border-radius: 50%; display: flex; align-items: center;
    justify-content: center; font-size: 14px; font-weight: bold; flex-shrink: 0;
    border: 2px solid;
  }}
  .chain-actor-name {{ font-size: 13px; font-weight: bold; color: var(--text); flex: 1; }}
  .chain-actor-summary {{ font-size: 10px; color: var(--subtext); margin-top: 2px; }}
  .chain-expand-icon {{ color: var(--subtext); font-size: 12px; transition: transform 0.2s; }}
  .chain-card.open .chain-expand-icon {{ transform: rotate(180deg); }}
  .chain-card-body {{ display: none; padding: 0 16px 16px; }}
  .chain-card.open .chain-card-body {{ display: block; }}
  .chain-signal-list {{ display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }}
  .chain-signal {{
    border-radius: 8px; padding: 10px 14px; border-left: 4px solid;
  }}
  .chain-signal .sig-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }}
  .chain-signal .sig-title {{ font-size: 11px; font-weight: bold; color: var(--text); }}
  .chain-signal .sig-meta {{ font-size: 9px; color: var(--subtext); }}
  .chain-signal .sig-explanation {{ font-size: 10px; color: var(--subtext); line-height: 1.6; margin-bottom: 6px; }}
  .chain-signal .sig-evidence {{ font-size: 10px; color: var(--yellow); background: var(--surface2); border-radius: 4px; padding: 6px 8px; }}
  .chain-sev-CRÍTICO   {{ background: #2a0a12; border-color: var(--red); }}
  .chain-sev-ALTO      {{ background: #2a1a0a; border-color: var(--orange); }}
  .chain-sev-MEDIO     {{ background: #2a2a0a; border-color: var(--yellow); }}
  .chain-sev-BAJO      {{ background: #0a1a2a; border-color: var(--blue); }}

  /* ── GLOSSARY ─────────────────────────────────────────────────────────── */
  .glossary-search {{ background: var(--surface2); border: 1px solid var(--overlay); color: var(--text); padding: 8px 12px; border-radius: 6px; width: 280px; font-size: 12px; margin-bottom: 16px; font-family: inherit; }}
  .glossary-search::placeholder {{ color: var(--subtext); }}
  .glossary-tabs {{ display: flex; gap: 0; margin-bottom: 16px; border-bottom: 1px solid var(--overlay); }}
  .glossary-tab {{ padding: 8px 20px; font-size: 11px; color: var(--subtext); cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; font-family: inherit; background: none; border-top: none; border-left: none; border-right: none; }}
  .glossary-tab.active {{ color: var(--cyan); border-bottom-color: var(--cyan); }}
  .glossary-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(380px,1fr)); gap: 10px; }}
  .glossary-entry {{
    background: var(--surface); border: 1px solid var(--overlay); border-radius: 8px; padding: 12px 14px;
  }}
  .glossary-entry.hidden {{ display: none; }}
  .glossary-key {{ font-size: 11px; font-weight: bold; color: var(--cyan); margin-bottom: 4px; }}
  .glossary-abbr-key {{ font-size: 11px; font-weight: bold; color: var(--yellow); margin-bottom: 4px; font-family: monospace; }}
  .glossary-def {{ font-size: 10px; color: var(--subtext); line-height: 1.6; }}
</style>
</head>
<body>

<header>
  <div>
    <div style="color:var(--subtext);font-size:10px;letter-spacing:2px">◈ NULLSEC RED TEAM · FBSCRAP · SOCIAL INTELLIGENCE</div>
    <h1>▶ {target}</h1>
  </div>
  <div class="meta">
    <div style="color:var(--cyan);font-size:13px;font-weight:bold">INTELLIGENCE DASHBOARD</div>
    <div>{date_lbl}</div>
    <div style="color:var(--purple)">◈ NULLSEC RED TEAM · OSINT · CIB Intelligence</div>
  </div>
</header>

<div class="container">

  <!-- ████ CIB CONFIDENCE SCORE — HERO METRIC ████ -->
  <div class="cib-hero" id="cib-hero-panel">
    <div class="cib-gauge-wrap">
      <div class="cib-gauge">
        <svg viewBox="0 0 160 160" width="160" height="160">
          <circle cx="80" cy="80" r="65" fill="none" stroke="#313244" stroke-width="14"/>
          <circle id="cib-gauge-arc" cx="80" cy="80" r="65" fill="none"
                  stroke="#f38ba8" stroke-width="14" stroke-linecap="round"
                  stroke-dasharray="408.41" stroke-dashoffset="408.41"
                  style="transition: stroke-dashoffset 1.2s cubic-bezier(0.4,0,0.2,1), stroke 0.6s"/>
        </svg>
        <div class="cib-gauge-val">
          <div class="score" id="cib-gauge-score" style="color:#f38ba8">0</div>
          <div class="max">/100</div>
        </div>
      </div>
      <div class="cib-label" id="cib-gauge-label" style="background:#3d1520;color:#f38ba8">ORGANIC</div>
      <div style="color:var(--subtext);font-size:9px;text-align:center;margin-top:4px" id="cib-engines-count"></div>
    </div>

    <div class="cib-center">
      <div style="color:var(--purple);font-size:10px;letter-spacing:2px;margin-bottom:8px">CIB UNIFIED CONFIDENCE SCORE — ALL FORENSIC DIMENSIONS</div>
      <div class="cib-narrative" id="cib-narrative">Loading forensic analysis...</div>
      <div style="color:var(--subtext);font-size:10px;font-weight:bold;letter-spacing:1px;margin-bottom:8px">KEY SIGNALS:</div>
      <div class="cib-signals" id="cib-signals-list"></div>
    </div>

    <div class="cib-dims" id="cib-dims-panel">
      <div style="color:var(--subtext);font-size:10px;letter-spacing:1px;margin-bottom:8px;text-align:center">DIMENSION BREAKDOWN</div>
    </div>
  </div>

  <!-- METRICS -->
  <div class="section">
    <div class="section-title">◈ Overview Metrics</div>
    <div class="metrics-grid" id="metrics-grid"></div>
  </div>

  <!-- TIMELINE + HCS CHARTS -->
  <div class="section">
    <div class="section-title">◈ Attack Timeline · HCS Distribution</div>
    <div class="charts-row">
      <div class="chart-box">
        <h3>SENTIMENT TIMELINE</h3>
        <canvas id="timeline-chart"></canvas>
      </div>
      <div class="chart-box">
        <h3>HUMAN CONFIDENCE SCORE (HCS) DISTRIBUTION</h3>
        <canvas id="hcs-chart"></canvas>
      </div>
    </div>
  </div>

  <!-- CIB NETWORK -->
  <div class="section">
    <div class="section-title">◈ CIB Network — Coordinated Inauthentic Behavior Graph</div>
    <div id="cib-network"></div>
    <div class="legend">
      <div class="legend-item"><div class="legend-dot" style="background:#f38ba8"></div> COMMAND</div>
      <div class="legend-item"><div class="legend-dot" style="background:#fab387"></div> AMPLIFIER</div>
      <div class="legend-item"><div class="legend-dot" style="background:#f9e2af"></div> BOT CLUSTER</div>
      <div class="legend-item"><div class="legend-dot" style="background:#89b4fa"></div> HUB</div>
      <div class="legend-item"><div class="legend-dot" style="background:#45475a"></div> PERIPHERAL</div>
    </div>
    <div class="tooltip" id="tooltip"></div>
  </div>

  <!-- OWNERSHIP ATTRIBUTION -->
  <div class="section">
    <div class="section-title">◈ Ownership Attribution — Operadores Detectados</div>
    <div id="ownership-summary" style="color:var(--yellow);margin-bottom:12px;font-size:12px"></div>
    <div class="op-grid" id="op-grid"></div>
    <div style="margin-top:16px">
      <div class="section-title" style="font-size:11px">PÁGINAS DE ATAQUE DETECTADAS</div>
      <div class="atk-page-list" id="atk-pages"></div>
    </div>
  </div>

  <!-- TEMPORAL ATTACK WAVES -->
  <div class="section">
    <div class="section-title">⏱ Temporal Attack Wave Detector — P2</div>
    <div id="temporal-summary" style="color:var(--yellow);margin-bottom:12px;font-size:12px"></div>
    <div class="charts-row" style="margin-bottom:16px">
      <div class="chart-box">
        <h3>COMMENT ACTIVITY TIMELINE (HOURLY)</h3>
        <canvas id="temporal-chart"></canvas>
      </div>
      <div class="chart-box" id="waves-panel">
        <h3>ATTACK WAVES</h3>
        <div id="waves-list" style="overflow-y:auto;max-height:200px;font-size:11px"></div>
      </div>
    </div>
    <div id="sync-pairs-panel" style="display:none">
      <div style="color:var(--orange);font-weight:bold;font-size:11px;margin-bottom:6px">⚡ ULTRA-SYNC PAIRS (≤3s — statistically impossible organically)</div>
      <div id="sync-pairs-list" style="font-size:10px;color:var(--subtext)"></div>
    </div>
  </div>

  <!-- STYLOMETRIC FINGERPRINTING -->
  <div class="section">
    <div class="section-title">🖋 Stylometric Fingerprinting — P3</div>
    <div id="stylo-summary" style="color:var(--purple);margin-bottom:12px;font-size:12px"></div>
    <div class="op-grid" id="stylo-clusters"></div>
    <div id="stylo-copypaste" style="margin-top:14px;display:none">
      <div style="color:var(--red);font-weight:bold;font-size:11px;margin-bottom:6px">📋 COPY-PASTE TEMPLATES</div>
      <div id="stylo-cp-list" style="font-size:10px"></div>
    </div>
  </div>

  <!-- SENTIMENT MANIPULATION DELTA -->
  <div class="section">
    <div class="section-title">📊 Sentiment Manipulation Delta — P6</div>
    <div id="sentiment-summary" style="color:var(--orange);margin-bottom:12px;font-size:12px"></div>
    <div class="charts-row" style="margin-bottom:16px">
      <div class="chart-box" id="seeded-posts-panel">
        <h3>SEEDED / REVERSED POSTS</h3>
        <div id="seeded-list" style="overflow-y:auto;max-height:220px;font-size:10px"></div>
      </div>
      <div class="chart-box">
        <h3>TOP SEED ACCOUNTS</h3>
        <div id="seed-accounts-list" style="overflow-y:auto;max-height:220px;font-size:10px"></div>
      </div>
    </div>
  </div>

  <!-- FIRST MOVER SEEDING -->
  <div class="section">
    <div class="section-title">🚀 First-Mover Seeding Analysis — N1</div>
    <div id="firstmover-summary" style="color:var(--cyan);margin-bottom:12px;font-size:12px"></div>
    <div class="op-grid" id="seed-accounts-grid"></div>
    <div id="seeding-teams-panel" style="margin-top:14px;display:none">
      <div style="color:var(--orange);font-weight:bold;font-size:11px;margin-bottom:6px">👥 SEEDING TEAMS — actors who co-seed the same posts</div>
      <div id="seeding-teams-list" style="font-size:10px"></div>
    </div>
  </div>

  <!-- SEMANTIC NARRATIVE CLUSTERS -->
  <div class="section">
    <div class="section-title">🧠 Semantic Narrative Cluster Analysis — N5</div>
    <div id="semantic-summary" style="color:var(--purple);margin-bottom:12px;font-size:12px"></div>
    <div class="op-grid" id="semantic-clusters-grid"></div>
    <div id="semantic-roles-panel" style="margin-top:14px;display:none">
      <div style="color:var(--orange);font-weight:bold;font-size:11px;margin-bottom:4px">AMPLIFIERS &amp; SOLDIERS</div>
      <div id="semantic-roles-list" style="font-size:10px"></div>
    </div>
  </div>

  <!-- LEGAL EVIDENCE PACKAGE -->
  <div class="section">
    <div class="section-title">⚖️ Legal Evidence Package — N8 Chain-of-Custody</div>
    <div id="legal-summary-box" style="background:var(--surface);border:1px solid var(--overlay);border-radius:8px;padding:16px"></div>
  </div>

  <!-- ACCOUNT LIFECYCLE ANOMALY DETECTOR -->
  <div class="section">
    <div class="section-title">💤 Account Lifecycle Anomaly Detector — P4</div>
    <div id="lifecycle-summary" style="color:#cba6f7;margin-bottom:12px;font-size:12px"></div>
    <div id="lifecycle-cells-panel" style="margin-bottom:14px;display:none">
      <div style="color:#cba6f7;font-weight:bold;font-size:11px;margin-bottom:6px">⚡ COORDINATED SLEEPER CELLS — activated in synchronized windows</div>
      <div id="lifecycle-cells-list" style="font-size:10px"></div>
    </div>
    <div class="op-grid" id="lifecycle-actors-grid"></div>
  </div>

  <!-- NARRATIVE INJECTION POINT DETECTOR -->
  <div class="section">
    <div class="section-title">💉 Narrative Injection Point Detector — N3</div>
    <div id="injection-summary" style="color:var(--cyan);margin-bottom:12px;font-size:12px"></div>
    <div id="injection-injectors-panel" style="margin-bottom:10px">
      <div style="color:var(--cyan);font-weight:bold;font-size:11px;margin-bottom:4px">TOP INJECTORS</div>
      <div id="injection-injectors-list" style="font-size:10px;display:flex;flex-wrap:wrap;gap:6px"></div>
    </div>
    <div class="op-grid" id="injection-narratives-grid"></div>
    <div id="injection-chains-panel" style="margin-top:14px;display:none">
      <div style="color:var(--cyan);font-weight:bold;font-size:11px;margin-bottom:6px">🔗 PROPAGATION CHAINS — temporal spread of top narratives</div>
      <div id="injection-chains-list" style="font-size:10px"></div>
    </div>
  </div>

  <!-- INFLUENCE TOPOLOGY SCORE -->
  <div class="section">
    <div class="section-title">🕸 Influence Topology Score — P7</div>
    <div id="topology-summary" style="color:var(--cyan);margin-bottom:12px;font-size:12px"></div>
    <div class="charts-row" style="margin-bottom:16px">
      <div class="chart-box">
        <h3>COMMAND CHAIN + AMPLIFIERS</h3>
        <div id="topology-roles-list" style="overflow-y:auto;max-height:220px;font-size:10px"></div>
      </div>
      <div class="chart-box">
        <h3>INFLUENCE COMMUNITIES</h3>
        <div id="topology-comms-list" style="overflow-y:auto;max-height:220px;font-size:10px"></div>
      </div>
    </div>
    <div class="op-grid" id="topology-actors-grid"></div>
  </div>

  <!-- HASHTAG WEAPONIZATION DETECTOR -->
  <div class="section">
    <div class="section-title"># Hashtag Weaponization Detector — N2</div>
    <div id="hashtag-summary" style="color:var(--yellow);margin-bottom:12px;font-size:12px"></div>
    <div id="hashtag-weaponized-panel" style="margin-bottom:12px;display:none">
      <div style="color:var(--red);font-weight:bold;font-size:11px;margin-bottom:6px">⚠ WEAPONIZED HASHTAGS — coordinated non-organic adoption</div>
      <div id="hashtag-tags-list" style="display:flex;flex-wrap:wrap;gap:6px"></div>
    </div>
    <div id="hashtag-seeders-panel" style="margin-bottom:12px;display:none">
      <div style="color:var(--orange);font-weight:bold;font-size:11px;margin-bottom:4px">TOP SEEDERS</div>
      <div id="hashtag-seeders-list" style="font-size:10px;display:flex;flex-wrap:wrap;gap:6px"></div>
    </div>
    <div class="op-grid" id="hashtag-profiles-grid"></div>
  </div>

  <!-- E1: IDENTITY PERSISTENCE TRACKER -->
  <div class="section">
    <div class="section-title">🧬 Identity Persistence Tracker — E1</div>
    <div id="identity-summary" style="color:var(--red);margin-bottom:12px;font-size:12px"></div>
    <div id="identity-stats" style="display:flex;gap:12px;margin-bottom:12px;flex-wrap:wrap"></div>
    <div class="op-grid" id="identity-morphs-grid"></div>
  </div>

  <!-- E8: NARRATIVE MUTATION TRACKER -->
  <div class="section">
    <div class="section-title">🧠 Narrative Mutation Tracker — E8</div>
    <div id="mutation-summary" style="color:var(--orange);margin-bottom:8px;font-size:12px"></div>
    <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap" id="mutation-type-badges"></div>
    <div style="height:150px;margin-bottom:12px"><canvas id="mutation-intensity-chart"></canvas></div>
    <div class="op-grid" id="mutation-events-grid"></div>
  </div>

  <!-- E5: DARK AMPLIFICATION TRACKER -->
  <div class="section">
    <div class="section-title">⚡ Dark Amplification Tracker — E5</div>
    <div id="darkamp-summary" style="color:var(--orange);margin-bottom:12px;font-size:12px"></div>
    <div class="op-grid" id="darkamp-events-grid"></div>
  </div>

  <!-- E7: BOT FARM SHIFT DETECTOR -->
  <div class="section">
    <div class="section-title">🔄 Bot Farm Shift Detector — E7</div>
    <div id="shift-summary" style="color:var(--red);margin-bottom:12px;font-size:12px"></div>
    <div style="height:140px;margin-bottom:12px">
      <canvas id="shift-timeline-chart"></canvas>
    </div>
    <div class="op-grid" id="shift-events-grid"></div>
  </div>

  <!-- E2: REPLY-CHAIN HIJACK DETECTOR -->
  <div class="section">
    <div class="section-title">🎯 Reply-Chain Hijack Detector — E2</div>
    <div id="reply-summary" style="color:var(--orange);margin-bottom:12px;font-size:12px"></div>
    <div id="reply-career" style="margin-bottom:10px"></div>
    <div class="op-grid" id="reply-posts-grid"></div>
  </div>

  <!-- E6: CROSS-CAMPAIGN ACTOR PERSISTENCE -->
  <div class="section">
    <div class="section-title">🔄 Cross-Campaign Actor Persistence — E6</div>
    <div id="cross-summary" style="color:var(--purple);margin-bottom:12px;font-size:12px"></div>
    <div id="cross-stats" style="display:flex;gap:16px;margin-bottom:12px;flex-wrap:wrap"></div>
    <div class="op-grid" id="cross-actors-grid"></div>
  </div>

  <!-- E4: ENGAGEMENT ANOMALY INDEX -->
  <div class="section">
    <div class="section-title">📊 Engagement Anomaly Index — E4</div>
    <div id="engagement-summary" style="color:var(--orange);margin-bottom:12px;font-size:12px"></div>
    <div class="op-grid" id="engagement-posts-grid"></div>
  </div>

  <!-- E3: EMOTIONAL CONTAGION SCORE -->
  <div class="section">
    <div class="section-title">🧠 Emotional Contagion Score — E3</div>
    <div id="contagion-summary" style="color:var(--red);margin-bottom:8px;font-size:12px"></div>
    <div style="display:flex;align-items:center;gap:16px;margin-bottom:12px">
      <div style="color:var(--subtext);font-size:11px">SHIFT DIRECTION:</div>
      <div id="contagion-direction" style="font-size:14px;font-weight:bold"></div>
    </div>
    <div style="height:180px;margin-bottom:16px">
      <canvas id="contagion-chart"></canvas>
    </div>
    <div style="color:var(--yellow);font-size:11px;font-weight:bold;margin-bottom:8px">MOST CONTAMINATED THREADS</div>
    <div class="op-grid" id="contagion-posts-grid"></div>
  </div>

  <!-- TROLLHUNTER: MEXICAN POLITICAL CIB DETECTOR -->
  <div class="section">
    <div class="section-title">🎯 TrollHunter — Mexican Political CIB Detector</div>
    <div id="troll-summary" style="color:var(--red);margin-bottom:12px;font-size:12px"></div>

    <!-- stat badges -->
    <div id="troll-badges" style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px"></div>

    <!-- filter bar -->
    <div style="margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap">
      <button onclick="trollFilter('ALL')"     class="filter-btn active" id="fb-all">ALL</button>
      <button onclick="trollFilter('CONFIRMED_BOT')" class="filter-btn" id="fb-bot" style="color:#f38ba8">⛔ CONFIRMED</button>
      <button onclick="trollFilter('HIGH_RISK')"     class="filter-btn" id="fb-hr"  style="color:#fab387">🔴 HIGH RISK</button>
      <button onclick="trollFilter('SUSPICIOUS')"    class="filter-btn" id="fb-sus" style="color:#f9e2af">🟡 SUSPICIOUS</button>
      <button onclick="trollFilter('LIKELY_HUMAN')"  class="filter-btn" id="fb-lh"  style="color:#89b4fa">🔵 LIKELY HUMAN</button>
    </div>

    <div id="troll-profiles-grid" class="op-grid"></div>
  </div>

  <!-- ACCOUNT VELOCITY PROFILE -->
  <div class="section">
    <div class="section-title">⚡ Account Velocity Profile — N4</div>
    <div id="velocity-summary" style="color:var(--cyan);margin-bottom:12px;font-size:12px"></div>
    <div class="charts-row" style="margin-bottom:16px">
      <div class="chart-box">
        <h3>BOT VELOCITY ACTORS</h3>
        <div id="velocity-bot-list" style="overflow-y:auto;max-height:200px;font-size:10px"></div>
      </div>
      <div class="chart-box">
        <h3>SUSPICIOUS ACTORS</h3>
        <div id="velocity-susp-list" style="overflow-y:auto;max-height:200px;font-size:10px"></div>
      </div>
    </div>
    <div class="op-grid" id="velocity-actors-grid"></div>
  </div>

  <!-- CROSS-POST NARRATIVE SEEDING -->
  <div class="section">
    <div class="section-title">🌱 Cross-Post Narrative Seeding — P5</div>
    <div id="seeding-summary" style="color:var(--green);margin-bottom:12px;font-size:12px"></div>
    <div id="seeding-cross-panel" style="margin-bottom:12px;display:none">
      <div style="color:var(--orange);font-weight:bold;font-size:11px;margin-bottom:6px">CROSS-POST ACTORS (3+ posts)</div>
      <div id="seeding-cross-list" style="display:flex;flex-wrap:wrap;gap:6px"></div>
    </div>
    <div class="op-grid" id="seeding-seeds-grid"></div>
  </div>

  <!-- CROSS-POST TIME CORRELATION -->
  <div class="section">
    <div class="section-title">🔗 Cross-Post Time Correlation — N6</div>
    <div id="correlation-summary" style="color:var(--orange);margin-bottom:12px;font-size:12px"></div>
    <div id="correlation-pairs-panel" style="margin-bottom:12px;display:none">
      <div style="color:var(--red);font-weight:bold;font-size:11px;margin-bottom:6px">HIGH CORRELATION PAIRS — coordinated amplification across posts</div>
      <div class="op-grid" id="correlation-pairs-grid"></div>
    </div>
  </div>

  <!-- BOT OPERATOR ATTRIBUTION -->
  <div class="section">
    <div class="section-title">🕵 Bot Operator Attribution — N7</div>
    <div id="attribution-summary" style="color:var(--purple);margin-bottom:12px;font-size:12px"></div>
    <div class="op-grid" id="attribution-operators-grid"></div>
  </div>

  <!-- MULTI-SOURCE CROSS-PAGE CIB MATRIX -->
  <div class="section" id="multi-source-section" style="display:none">
    <div class="section-title">🌐 Multi-Source Cross-Page CIB Matrix</div>
    <div class="ms-header">
      <div style="color:var(--subtext);font-size:11px" id="ms-summary-text"></div>
      <div class="ms-score-pill" id="ms-score-pill"></div>
    </div>
    <div class="ms-pair-grid" id="ms-pair-grid"></div>
    <div id="ms-cross-actors-panel" style="display:none;margin-top:16px">
      <div style="color:var(--orange);font-weight:bold;font-size:11px;margin-bottom:8px">
        🎯 ACTORES DETECTADOS EN MÚLTIPLES PÁGINAS SIMULTÁNEAMENTE
      </div>
      <div style="overflow-x:auto">
        <table id="ms-cross-table">
          <thead><tr>
            <th>ACTOR</th><th>PÁGINAS</th><th>RIESGO</th><th>BOT SCORE</th><th>PÁGINAS ACTIVAS</th>
          </tr></thead>
          <tbody id="ms-cross-tbody"></tbody>
        </table>
      </div>
    </div>
    <div id="ms-sync-terms-panel" style="display:none;margin-top:16px">
      <div style="color:var(--purple);font-size:10px;font-weight:bold;margin-bottom:6px">
        📌 TÉRMINOS DE NARRATIVA SINCRONIZADA EN TODAS LAS PÁGINAS:
      </div>
      <div class="ms-sync-terms" id="ms-sync-terms-list"></div>
    </div>
  </div>

  <!-- CONFIDENCE CHAIN — CADENAS DE EVIDENCIA FORENSE POR ACTOR -->
  <div class="section" id="chain-section" style="display:none">
    <div class="section-title">🔍 Cadenas de Evidencia Forense por Actor</div>
    <div style="color:var(--subtext);font-size:11px;margin-bottom:16px;font-style:italic">
      Explicación no-técnica de POR QUÉ cada cuenta fue clasificada como bot o troll.
      Diseñado para fiscales, jueces y periodistas.
    </div>
    <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:12px">
      <input class="chain-search" type="text" id="chain-search" placeholder="🔎 Buscar actor...">
      <div class="chain-filters" id="chain-filter-btns">
        <button class="filter-btn active" data-cls="ALL" onclick="filterChains(this)">TODOS</button>
        <button class="filter-btn" data-cls="CONFIRMED_BOT" onclick="filterChains(this)" style="color:var(--red)">BOT CONFIRMADO</button>
        <button class="filter-btn" data-cls="HIGH_RISK" onclick="filterChains(this)" style="color:var(--orange)">ALTO RIESGO</button>
        <button class="filter-btn" data-cls="SUSPICIOUS" onclick="filterChains(this)" style="color:var(--yellow)">SOSPECHOSO</button>
      </div>
    </div>
    <div class="chain-cards" id="chain-cards-container"></div>
  </div>

  <!-- BOT SUSPECTS TABLE -->
  <div class="section">
    <div class="section-title">◈ Bot Suspects — Análisis Forense Completo</div>
    <input type="text" class="search-box" id="suspect-search" placeholder="Buscar actor...">
    <div class="scroll-x">
      <table>
        <thead>
          <tr>
            <th onclick="sortTable(0)"># ↕</th>
            <th onclick="sortTable(1)">ACTOR ↕</th>
            <th onclick="sortTable(2)">BOT SCORE ↕</th>
            <th onclick="sortTable(3)">HCS ↕</th>
            <th onclick="sortTable(4)">ATAQUES ↕</th>
            <th onclick="sortTable(5)">POSTS ↕</th>
            <th>CROSS-MEDIA</th>
            <th>SEÑALES</th>
            <th>MUESTRA</th>
          </tr>
        </thead>
        <tbody id="suspects-tbody"></tbody>
      </table>
    </div>
  </div>

</div>

<script>
const DATA = {data_json};

// ── Metrics ──────────────────────────────────────────────────────────────────
const m = DATA.metrics;
const metricCards = [
  {{ v: m.total_posts,  l: 'TOTAL POSTS',     cls: 'blue'   }},
  {{ v: m.neg_pct+'%',  l: 'NEGATIVIDAD',     cls: m.neg_pct >= 70 ? 'red' : 'orange' }},
  {{ v: m.bot_pct+'%',  l: 'BOTS CONFIRMADOS',cls: m.bot_pct >= 40 ? 'red' : 'yellow' }},
  {{ v: m.coord_score,  l: 'COORDINACIÓN /100',cls: m.coord_score >= 70 ? 'red' : 'orange' }},
  {{ v: m.mean_hcs,     l: 'MEAN HCS',        cls: m.mean_hcs <= 40 ? 'red' : 'cyan' }},
  {{ v: m.total_actors, l: 'ACTORES RED',      cls: 'purple' }},
  {{ v: m.total_edges,  l: 'ARISTAS GRAFO',    cls: 'purple' }},
  {{ v: m.operators,    l: 'OPERADORES DET.',  cls: m.operators > 0 ? 'red' : 'green' }},
  {{ v: m.attack_pages,    l: 'PÁGINAS ATAQUE',    cls: m.attack_pages > 0 ? 'orange' : 'green' }},
  {{ v: m.temporal_score,  l: 'TEMPORAL SCORE /100',cls: m.temporal_score >= 60 ? 'red' : m.temporal_score >= 30 ? 'orange' : 'green' }},
  {{ v: m.attack_waves,    l: 'ATTACK WAVES DET.',  cls: m.attack_waves > 0 ? 'red' : 'green' }},
  {{ v: m.stylo_clusters,  l: 'STYLO CLUSTERS',     cls: m.stylo_clusters > 0 ? 'purple' : 'green' }},
  {{ v: m.stylo_bots,      l: 'BOT-TEMPLATE WRITERS',cls: m.stylo_bots > 0 ? 'orange' : 'green' }},
  {{ v: m.sentiment_score, l: 'SENTIMENT MANIP /100',cls: m.sentiment_score >= 60 ? 'red' : m.sentiment_score >= 30 ? 'orange' : 'green' }},
  {{ v: m.seeded_posts,    l: 'SEEDED POSTS DET.',   cls: m.seeded_posts > 0 ? 'red' : 'green' }},
  {{ v: m.seed_accounts,   l: 'SEED ACCOUNTS',       cls: m.seed_accounts > 0 ? 'orange' : 'green' }},
  {{ v: m.narrative_score, l: 'NARRATIVE SCORE /100',cls: m.narrative_score >= 60 ? 'red' : m.narrative_score >= 30 ? 'orange' : 'green' }},
  {{ v: m.bot_clusters,    l: 'BOT-DOM CLUSTERS',    cls: m.bot_clusters > 0 ? 'red' : 'green' }},
  {{ v: m.lifecycle_score, l: 'LIFECYCLE ANOMALY /100',cls: m.lifecycle_score >= 60 ? 'red' : m.lifecycle_score >= 30 ? 'orange' : 'green' }},
  {{ v: m.sleeper_accounts,l: 'SLEEPER ACCOUNTS',     cls: m.sleeper_accounts > 0 ? 'red' : 'green' }},
  {{ v: m.sleeper_cells,   l: 'SLEEPER CELLS',        cls: m.sleeper_cells > 0 ? 'red' : 'green' }},
  {{ v: m.injection_score, l: 'NARR INJECT /100',     cls: m.injection_score >= 60 ? 'red' : m.injection_score >= 30 ? 'orange' : 'green' }},
  {{ v: m.narratives_found,l: 'NARRATIVES DETECTED',  cls: m.narratives_found > 0 ? 'orange' : 'green' }},
  {{ v: m.topology_score,  l: 'TOPOLOGY SCORE /100',  cls: m.topology_score >= 60 ? 'red' : m.topology_score >= 30 ? 'orange' : 'green' }},
  {{ v: (m.pagerank_gini||0).toFixed(3), l: 'PR GINI CONC.', cls: (m.pagerank_gini||0) >= 0.6 ? 'red' : (m.pagerank_gini||0) >= 0.35 ? 'orange' : 'green' }},
  {{ v: m.hashtag_score,   l: 'HASHTAG WEAP /100',   cls: m.hashtag_score >= 60 ? 'red' : m.hashtag_score >= 30 ? 'orange' : 'green' }},
  {{ v: m.weaponized_tags, l: 'WEAPONIZED TAGS',      cls: m.weaponized_tags > 0 ? 'red' : 'green' }},
  {{ v: m.troll_score,     l: 'TROLL RISK /100',      cls: m.troll_score >= 60 ? 'red' : m.troll_score >= 30 ? 'orange' : 'green' }},
  {{ v: m.confirmed_bots,  l: 'CONFIRMED BOTS',       cls: m.confirmed_bots > 0 ? 'red' : 'green' }},
  {{ v: m.foreign_name_actors, l: 'FOREIGN-NAME ACCTS', cls: m.foreign_name_actors > 0 ? 'red' : 'green' }},
  {{ v: m.page_operators,  l: 'PAGE OPERATORS',       cls: m.page_operators > 0 ? 'orange' : 'green' }},
  {{ v: m.velocity_score,  l: 'VELOCITY SCORE /100',  cls: m.velocity_score >= 60 ? 'red' : m.velocity_score >= 30 ? 'orange' : 'green' }},
  {{ v: m.bot_velocity_actors, l: 'BOT VELOCITY ACTORS', cls: m.bot_velocity_actors > 0 ? 'red' : 'green' }},
  {{ v: m.seeding_score,   l: 'SEEDING SCORE /100',   cls: m.seeding_score >= 60 ? 'red' : m.seeding_score >= 30 ? 'orange' : 'green' }},
  {{ v: m.seeded_narratives, l: 'SEEDED NARRATIVES',  cls: m.seeded_narratives > 0 ? 'orange' : 'green' }},
  {{ v: m.correlation_score, l: 'CORRELATION /100',   cls: m.correlation_score >= 60 ? 'red' : m.correlation_score >= 30 ? 'orange' : 'green' }},
  {{ v: m.high_corr_pairs, l: 'HIGH CORR PAIRS',      cls: m.high_corr_pairs > 0 ? 'red' : 'green' }},
  {{ v: m.attribution_score, l: 'BOT ATTR /100',      cls: m.attribution_score >= 60 ? 'red' : m.attribution_score >= 30 ? 'orange' : 'green' }},
  {{ v: m.attributed_operators, l: 'OPERATORS FOUND', cls: m.attributed_operators > 0 ? 'red' : 'green' }},
  {{ v: m.engagement_score,  l: 'ENGAGEMENT ANOM /100', cls: m.engagement_score >= 60 ? 'red' : m.engagement_score >= 30 ? 'orange' : 'green' }},
  {{ v: m.bot_boosted_posts, l: 'BOT-BOOSTED POSTS',    cls: m.bot_boosted_posts > 0 ? 'red' : 'green' }},
  {{ v: m.ghost_posts,       l: 'GHOST POSTS',           cls: m.ghost_posts > 0 ? 'orange' : 'green' }},
  {{ v: m.contagion_score,   l: 'CONTAGION SCORE /100', cls: m.contagion_score >= 60 ? 'red' : m.contagion_score >= 30 ? 'orange' : 'green' }},
  {{ v: m.contagion_direction, l: 'CONTAGION DIR',       cls: m.contagion_direction === 'NEGATIVE' ? 'red' : m.contagion_direction === 'POSITIVE' ? 'green' : 'orange' }},
  {{ v: m.contagion_affected, l: 'AFFECTED THREADS',    cls: m.contagion_affected > 0 ? 'orange' : 'green' }},
  {{ v: m.id_score,          l: 'IDENTITY MORPH /100',  cls: m.id_score >= 60 ? 'red' : m.id_score >= 30 ? 'orange' : 'green' }},
  {{ v: m.id_confirmed_morphs,l:'CONFIRMED MORPHS',     cls: m.id_confirmed_morphs > 0 ? 'red' : 'green' }},
  {{ v: m.id_unique_operators,l:'UNIQUE OPERATORS',     cls: 'cyan' }},
  {{ v: m.mut_score,         l: 'MUTATION SCORE /100',  cls: m.mut_score >= 60 ? 'red' : m.mut_score >= 30 ? 'orange' : 'green' }},
  {{ v: m.mut_pivot,         l: 'PIVOT EVENTS',         cls: m.mut_pivot > 0 ? 'red' : 'green' }},
  {{ v: m.mut_total,         l: 'TOTAL MUTATIONS',      cls: m.mut_total > 0 ? 'orange' : 'green' }},
  {{ v: m.da_score,          l: 'DARK AMP /100',        cls: m.da_score >= 60 ? 'red' : m.da_score >= 30 ? 'orange' : 'green' }},
  {{ v: m.da_dark_posts,    l: 'DARK AMP POSTS',       cls: m.da_dark_posts > 0 ? 'red' : 'green' }},
  {{ v: Math.round(m.da_baseline)+'e/h', l: 'VELOCITY BASELINE', cls: 'cyan' }},
  {{ v: m.sh_score,          l: 'SHIFT DETECT /100',   cls: m.sh_score >= 60 ? 'red' : m.sh_score >= 30 ? 'orange' : 'green' }},
  {{ v: m.sh_confirmed,      l: 'CONFIRMED SHIFTS',    cls: m.sh_confirmed > 0 ? 'red' : 'green' }},
  {{ v: m.sh_rotated,        l: 'ACTORS ROTATED',      cls: m.sh_rotated > 0 ? 'orange' : 'green' }},
  {{ v: m.rc_score,          l: 'REPLY HIJACK /100',   cls: m.rc_score >= 60 ? 'red' : m.rc_score >= 30 ? 'orange' : 'green' }},
  {{ v: m.rc_hijacked_posts, l: 'HIJACKED THREADS',    cls: m.rc_hijacked_posts > 0 ? 'red' : 'green' }},
  {{ v: m.rc_career_hijackers,l:'CAREER HIJACKERS',    cls: m.rc_career_hijackers > 0 ? 'red' : 'green' }},
  {{ v: m.cc_score,          l: 'CROSS-CAMPAIGN /100', cls: m.cc_score >= 60 ? 'red' : m.cc_score >= 30 ? 'orange' : 'green' }},
  {{ v: m.cc_professional,   l: 'PROFESSIONAL TROLLS', cls: m.cc_professional > 0 ? 'red' : 'green' }},
  {{ v: m.cc_total_tracked,  l: 'ACTORS IN REGISTRY',  cls: m.cc_total_tracked > 0 ? 'cyan' : 'green' }},
];
const mg = document.getElementById('metrics-grid');
metricCards.forEach(c => {{
  mg.innerHTML += `<div class="metric-card"><div class="value ${{c.cls}}">${{c.v}}</div><div class="label">${{c.l}}</div></div>`;
}});

// ── Timeline Chart ────────────────────────────────────────────────────────────
const tl = DATA.timeline;
if (tl.dates && tl.dates.length) {{
  new Chart(document.getElementById('timeline-chart'), {{
    type: 'line',
    data: {{
      labels: tl.dates,
      datasets: [
        {{ label: 'Negativo/Agresivo', data: tl.negative, borderColor: '#f38ba8', backgroundColor: 'rgba(243,139,168,0.1)', tension: 0.3, fill: true }},
        {{ label: 'Positivo',          data: tl.positive, borderColor: '#a6e3a1', backgroundColor: 'rgba(166,227,161,0.1)', tension: 0.3, fill: true }},
        {{ label: 'Neutral',           data: tl.neutral,  borderColor: '#45475a', backgroundColor: 'rgba(69,71,90,0.1)',    tension: 0.3, fill: true }},
      ]
    }},
    options: {{ plugins: {{ legend: {{ labels: {{ color: '#cdd6f4', font: {{ family: 'Consolas', size: 10 }} }} }} }}, scales: {{ x: {{ ticks: {{ color: '#a6adc8', font: {{ size: 9 }} }}, grid: {{ color: '#313244' }} }}, y: {{ ticks: {{ color: '#a6adc8', font: {{ size: 9 }} }}, grid: {{ color: '#313244' }} }} }}, responsive: true, maintainAspectRatio: true }}
  }});
}}

// ── HCS Chart ─────────────────────────────────────────────────────────────────
const hcs = DATA.hcs;
if (hcs.labels && hcs.labels.length) {{
  new Chart(document.getElementById('hcs-chart'), {{
    type: 'bar',
    data: {{ labels: hcs.labels, datasets: [{{ data: hcs.counts, backgroundColor: hcs.colors, borderRadius: 4 }}] }},
    options: {{ plugins: {{ legend: {{ display: false }} }}, scales: {{ x: {{ ticks: {{ color: '#a6adc8', font: {{ size: 9 }} }}, grid: {{ color: '#313244' }} }}, y: {{ ticks: {{ color: '#a6adc8', font: {{ size: 9 }} }}, grid: {{ color: '#313244' }} }} }}, responsive: true }}
  }});
}}

// ── CIB Network D3 ────────────────────────────────────────────────────────────
(function() {{
  const cibData = DATA.cib;
  if (!cibData.nodes || cibData.nodes.length === 0) return;

  const el  = document.getElementById('cib-network');
  const tip = document.getElementById('tooltip');
  const W   = el.clientWidth  || 1200;
  const H   = el.clientHeight || 480;

  const svg = d3.select('#cib-network').append('svg');
  const g   = svg.append('g');

  // Zoom + pan
  svg.call(d3.zoom().scaleExtent([0.2, 6]).on('zoom', e => g.attr('transform', e.transform)));

  const sim = d3.forceSimulation(cibData.nodes)
    .force('link', d3.forceLink(cibData.links).id(d => d.id).distance(60).strength(0.4))
    .force('charge', d3.forceManyBody().strength(-120))
    .force('center', d3.forceCenter(W / 2, H / 2))
    .force('collide', d3.forceCollide(d => (d.radius || 6) + 4));

  const link = g.append('g').selectAll('line')
    .data(cibData.links).enter().append('line')
    .attr('stroke', '#45475a')
    .attr('stroke-opacity', 0.5)
    .attr('stroke-width', d => Math.max(0.5, (d.weight || 0.1) * 3));

  const node = g.append('g').selectAll('circle')
    .data(cibData.nodes).enter().append('circle')
    .attr('r', d => d.radius || 6)
    .attr('fill', d => d.color || '#45475a')
    .attr('stroke', '#1e1e2e')
    .attr('stroke-width', 1.5)
    .style('cursor', 'pointer')
    .call(d3.drag()
      .on('start', (ev, d) => {{ if (!ev.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }})
      .on('drag',  (ev, d) => {{ d.fx = ev.x; d.fy = ev.y; }})
      .on('end',   (ev, d) => {{ if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }})
    )
    .on('mouseover', (ev, d) => {{
      tip.style.opacity = '1';
      tip.style.left = (ev.offsetX + 12) + 'px';
      tip.style.top  = (ev.offsetY - 10) + 'px';
      tip.innerHTML = `<b style="color:#cba6f7">${{d.id}}</b><br>
        Role: <span style="color:${{d.color}}">${{d.role}}</span><br>
        Degree: ${{d.degree}}  PageRank: ${{(d.pagerank*1000).toFixed(2)}}<br>
        Bot Score: ${{d.suspect_score}}/99<br>
        Community: #${{d.community}}`;
    }})
    .on('mouseout', () => {{ tip.style.opacity = '0'; }});

  // Labels for high-degree nodes only
  const labels = g.append('g').selectAll('text')
    .data(cibData.nodes.filter(d => d.degree >= 3)).enter()
    .append('text').attr('class', 'node-label')
    .text(d => d.id.substring(0, 14) + (d.id.length > 14 ? '…' : ''));

  sim.on('tick', () => {{
    link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
    node.attr('cx', d => d.x).attr('cy', d => d.y);
    labels.attr('x', d => d.x + (d.radius || 6) + 2).attr('y', d => d.y + 3);
  }});
}})();

// ── Ownership ─────────────────────────────────────────────────────────────────
(function() {{
  const own = DATA.ownership;
  document.getElementById('ownership-summary').textContent = own.summary || '';

  const grid = document.getElementById('op-grid');
  (own.operators || []).forEach(op => {{
    const confColor = op.confidence >= 75 ? '#f38ba8' : op.confidence >= 50 ? '#fab387' : '#f9e2af';
    const pages_html = (op.pages || []).slice(0,5).map(p => `<span class="tag">${{p.substring(0,20)}}</span>`).join('');
    const bots_html  = (op.bots  || []).slice(0,6).map(b => `<span class="tag" style="color:#f38ba8">${{b.substring(0,18)}}</span>`).join('');
    const sigs_html  = (op.signals||[]).map(s=>`<div class="op-detail">▸ ${{s}}</div>`).join('');
    grid.innerHTML += `
      <div class="op-card">
        <h4>OPERADOR #${{op.id + 1}} — CONFIANZA ${{op.confidence}}/99</h4>
        <div class="conf-bar"><div class="conf-fill" style="width:${{op.confidence}}%;background:${{confColor}}"></div></div>
        <div class="op-detail" style="color:${{confColor}};font-weight:bold">${{op.label}} · ${{op.attacks}} ataques</div>
        <div style="margin-top:8px;font-size:10px;color:var(--subtext)">PÁGINAS CONTROLADAS:</div>
        <div style="margin:4px 0">${{pages_html}}</div>
        <div style="margin-top:6px;font-size:10px;color:var(--subtext)">BOTS ATRIBUIDOS:</div>
        <div style="margin:4px 0">${{bots_html}}</div>
        ${{sigs_html}}
      </div>`;
  }});

  const atkDiv = document.getElementById('atk-pages');
  (own.attack_pages || []).forEach(p => {{
    atkDiv.innerHTML += `<div class="atk-page">${{p}}</div>`;
  }});
}})();

// ── Bot Suspects Table ────────────────────────────────────────────────────────
(function() {{
  const tbody = document.getElementById('suspects-tbody');
  const suspects = DATA.suspects || [];

  const hcsLabel = h => {{
    if (h <= 19) return ['CONFIRMED BOT', 'badge-red'];
    if (h <= 39) return ['HIGH RISK',     'badge-orange'];
    if (h <= 59) return ['SUSPICIOUS',    'badge-yellow'];
    if (h <= 79) return ['LIKELY HUMAN',  'badge-blue'];
    return ['HUMAN', 'badge-green'];
  }};

  suspects.forEach((s, i) => {{
    const [hl, hc] = hcsLabel(s.hcs);
    const crossBadge = s.cross_media ? '<span class="badge badge-cross">★ CROSS</span>' : '';
    const scoreColor = s.score >= 70 ? '#f38ba8' : s.score >= 40 ? '#fab387' : '#f9e2af';
    const scoreBarW  = Math.max(4, s.score) + '%';
    const sigs = (s.signals||[]).join(' · ').substring(0,60);
    tbody.innerHTML += `<tr>
      <td style="color:var(--subtext)">${{i+1}}</td>
      <td style="font-weight:bold;color:${{s.score>=70?'#f38ba8':'var(--text)'}}">
        ${{s.author.substring(0,30)}}
      </td>
      <td>
        <span style="color:${{scoreColor}};font-weight:bold">${{s.score}}</span>
        <span class="score-bar" style="width:${{scoreBarW}};background:${{scoreColor}}"></span>
      </td>
      <td><span class="badge ${{hc}}">${{s.hcs}} ${{hl}}</span></td>
      <td style="color:var(--orange)">${{s.attacks}}x</td>
      <td style="color:var(--subtext)">${{s.posts}}p</td>
      <td>${{crossBadge}}</td>
      <td style="color:var(--subtext);font-size:10px">${{sigs}}</td>
      <td style="color:var(--subtext);font-size:10px;max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${{s.sample||''}}</td>
    </tr>`;
  }});

  // Search
  document.getElementById('suspect-search').addEventListener('input', function() {{
    const q = this.value.toLowerCase();
    document.querySelectorAll('#suspects-tbody tr').forEach(tr => {{
      tr.classList.toggle('hidden', !tr.textContent.toLowerCase().includes(q));
    }});
  }});
}})();

// ── Temporal Attack Waves ─────────────────────────────────────────────────────
(function() {{
  const td = DATA.temporal;
  if (!td) return;

  document.getElementById('temporal-summary').textContent = td.summary || '';

  // Hourly activity timeline chart
  if (td.timeline && td.timeline.length) {{
    const labels = td.timeline.map(t => t.time.slice(11)); // HH:00
    const counts = td.timeline.map(t => t.count);
    new Chart(document.getElementById('temporal-chart'), {{
      type: 'bar',
      data: {{ labels, datasets: [{{ label: 'Comments', data: counts, backgroundColor: '#f38ba8', borderRadius: 3 }}] }},
      options: {{ plugins: {{ legend: {{ display: false }} }}, scales: {{ x: {{ ticks: {{ color: '#a6adc8', font: {{ size: 8 }} }}, grid: {{ color: '#313244' }} }}, y: {{ ticks: {{ color: '#a6adc8', font: {{ size: 9 }} }}, grid: {{ color: '#313244' }} }} }}, responsive: true }}
    }});
  }} else {{
    document.getElementById('temporal-chart').parentElement.innerHTML = '<h3>COMMENT ACTIVITY TIMELINE</h3><div style="color:var(--subtext);font-size:10px;margin-top:40px;text-align:center">No timestamped comments available</div>';
  }}

  // Waves list
  const wl = document.getElementById('waves-list');
  if (td.waves && td.waves.length) {{
    td.waves.forEach(w => {{
      const intensity_color = w.intensity > 1.0 ? '#f38ba8' : w.intensity > 0.5 ? '#fab387' : '#f9e2af';
      wl.innerHTML += `<div style="padding:6px 0;border-bottom:1px solid var(--overlay)">
        <span style="color:var(--cyan);font-weight:bold">W-${{String(w.id).padStart(2,'0')}}</span>
        <span style="color:var(--subtext);margin:0 8px">${{w.start.slice(11,19)}} → ${{w.end.slice(11,19)}}</span>
        <span style="color:var(--orange)">${{w.participants.length}} actors</span>
        <span style="color:var(--subtext);margin:0 6px">·</span>
        <span style="color:var(--yellow)">${{w.event_count}} events</span>
        <span style="color:var(--subtext);margin:0 6px">·</span>
        <span style="color:${{intensity_color}};font-weight:bold">intensity ${{w.intensity.toFixed(2)}}</span>
      </div>`;
    }});
  }} else {{
    wl.innerHTML = '<div style="color:var(--subtext);font-size:10px;margin-top:20px;text-align:center">No coordinated waves detected</div>';
  }}

  // Sync pairs
  if (td.sync_pairs && td.sync_pairs.length) {{
    const spPanel = document.getElementById('sync-pairs-panel');
    const spList  = document.getElementById('sync-pairs-list');
    spPanel.style.display = 'block';
    td.sync_pairs.slice(0, 10).forEach(p => {{
      spList.innerHTML += `<div style="margin:3px 0">⚡ <span style="color:var(--red)">${{p.author_a.slice(0,25)}}</span> ↔ <span style="color:var(--red)">${{p.author_b.slice(0,25)}}</span> <span style="color:var(--orange)">(Δ${{p.delta_s}}s)</span></div>`;
    }});
  }}
}})();

// ── Stylometry ─────────────────────────────────────────────────────────────────
(function() {{
  const sd = DATA.stylo;
  if (!sd) return;

  document.getElementById('stylo-summary').textContent = sd.summary || '';

  // Clusters
  const grid = document.getElementById('stylo-clusters');
  (sd.clusters || []).forEach(cl => {{
    const clColor = cl.label === 'TEMPLATE_CAMPAIGN' ? '#f38ba8' : cl.label === 'CLONE_FARM' ? '#fab387' : '#89b4fa';
    const actors_html = (cl.actors || []).map(a => `<span class="tag" style="color:#f38ba8">${{a.slice(0,20)}}</span>`).join('');
    grid.innerHTML += `
      <div class="op-card" style="border-color:#3d1550">
        <h4 style="color:var(--purple)">CLUSTER C-${{String(cl.id).padStart(2,'0')}} — <span style="color:${{clColor}}">${{cl.label}}</span></h4>
        <div class="conf-bar"><div class="conf-fill" style="width:${{Math.round(cl.similarity*100)}}%;background:${{clColor}}"></div></div>
        <div class="op-detail" style="color:${{clColor}}">Cosine similarity: ${{cl.similarity.toFixed(4)}} · ${{cl.actors.length}} actors</div>
        <div style="margin-top:8px">${{actors_html}}</div>
      </div>`;
  }});

  // Copy-paste
  if (sd.copy_paste && sd.copy_paste.length) {{
    document.getElementById('stylo-copypaste').style.display = 'block';
    const cpList = document.getElementById('stylo-cp-list');
    sd.copy_paste.forEach(g => {{
      cpList.innerHTML += `<div style="margin:4px 0;padding:6px;background:var(--surface);border-radius:6px">
        <span style="color:var(--orange);font-weight:bold">[${{g.count}}× · ${{g.actors.length}} actors]</span>
        <span style="color:var(--yellow);font-style:italic"> "${{g.sig}}…"</span>
      </div>`;
    }});
  }}
}})();

// ── Sentiment Manipulation Delta ─────────────────────────────────────────────
(function() {{
  const sd = DATA.sentiment;
  if (!sd) return;

  document.getElementById('sentiment-summary').textContent = sd.summary || '';

  const seededList = document.getElementById('seeded-list');
  if (sd.seeded && sd.seeded.length) {{
    sd.seeded.forEach(s => {{
      const labelColor = s.label === 'SEEDED' ? '#f38ba8' : '#fab387';
      const w0 = s.windows[0], w2 = s.windows[2];
      const w0pct = w0 ? Math.round(w0.neg_ratio * 100) + '%' : '—';
      const w2pct = w2 ? Math.round(w2.neg_ratio * 100) + '%' : '—';
      seededList.innerHTML += `<div style="padding:5px 0;border-bottom:1px solid var(--overlay)">
        <span style="color:${{labelColor}};font-weight:bold">${{s.label}}</span>
        <span style="color:var(--orange);margin:0 8px">Δ${{s.delta > 0 ? '+' : ''}}${{s.delta.toFixed(3)}}</span>
        <span style="color:var(--subtext)">W0→W2: ${{w0pct}}→${{w2pct}}</span>
        <div style="color:var(--subtext);font-size:9px;margin-top:2px">${{s.url}}</div>
        <div style="color:var(--red);font-size:9px">${{s.actors.join(' · ').substring(0,80)}}</div>
      </div>`;
    }});
  }} else {{
    seededList.innerHTML = '<div style="color:var(--subtext);margin-top:20px;text-align:center">No seeded posts detected</div>';
  }}

  const saList = document.getElementById('seed-accounts-list');
  (sd.seed_accounts || []).forEach((a, i) => {{
    saList.innerHTML += `<div style="padding:3px 0;border-bottom:1px solid var(--overlay)">
      <span style="color:var(--yellow);font-weight:bold">${{i+1}}.</span>
      <span style="color:var(--red);margin-left:6px">${{a.substring(0,40)}}</span>
    </div>`;
  }});
  if (!sd.seed_accounts || !sd.seed_accounts.length) {{
    saList.innerHTML = '<div style="color:var(--subtext);margin-top:20px;text-align:center">No seed accounts identified</div>';
  }}
}})();

// ── First-Mover Seeding ───────────────────────────────────────────────────────
(function() {{
  const fd = DATA.first_mover;
  if (!fd) return;

  document.getElementById('firstmover-summary').textContent = fd.summary || '';

  const grid = document.getElementById('seed-accounts-grid');
  (fd.seed_accounts || []).forEach(p => {{
    const scoreColor = p.count >= 10 ? '#f38ba8' : p.count >= 5 ? '#fab387' : '#f9e2af';
    grid.innerHTML += `
      <div class="op-card" style="border-color:#003050">
        <h4 style="color:var(--cyan)">${{p.actor.substring(0,30)}}</h4>
        <div class="conf-bar"><div class="conf-fill" style="width:${{Math.min(p.count*10,100)}}%;background:${{scoreColor}}"></div></div>
        <div class="op-detail" style="color:${{scoreColor}}">Seeds: ${{p.count}} · Avg pos: ${{p.avg_pos}} · Posts: ${{p.posts}}</div>
        <div class="op-detail" style="margin-top:4px;font-style:italic">"${{p.sample}}"</div>
      </div>`;
  }});

  if (fd.teams && fd.teams.length) {{
    document.getElementById('seeding-teams-panel').style.display = 'block';
    const tl = document.getElementById('seeding-teams-list');
    fd.teams.forEach(t => {{
      tl.innerHTML += `<div style="margin:3px 0;padding:5px;background:var(--surface);border-radius:6px">
        <span style="color:var(--orange);font-weight:bold">TEAM ${{t.id}}</span>
        <span style="color:var(--subtext);margin:0 8px">${{t.posts}} shared posts</span>
        <span style="color:var(--yellow)">${{t.actors.join(' · ').substring(0,80)}}</span>
      </div>`;
    }});
  }}
}})();

// ── Semantic Narrative Clusters ───────────────────────────────────────────────
(function() {{
  const nd = DATA.semantic;
  if (!nd) return;

  document.getElementById('semantic-summary').textContent = nd.summary || '';

  const grid = document.getElementById('semantic-clusters-grid');
  (nd.clusters || []).forEach(cl => {{
    const lblColor = cl.label === 'BOT_DOMINATED' ? '#f38ba8' : cl.label === 'MIXED' ? '#fab387' : '#a6e3a1';
    const botPct   = Math.round(cl.bot_ratio * 100);
    const terms_html = (cl.top_terms || []).map(t => `<span class="tag">${{t}}</span>`).join('');
    grid.innerHTML += `
      <div class="op-card" style="border-color:#200040">
        <h4 style="color:var(--purple)">NC-${{String(cl.id).padStart(2,'0')}} — <span style="color:${{lblColor}}">${{cl.label}}</span></h4>
        <div class="conf-bar"><div class="conf-fill" style="width:${{botPct}}%;background:${{lblColor}}"></div></div>
        <div class="op-detail" style="color:${{lblColor}}">Size: ${{cl.size}} · Bot ratio: ${{botPct}}% · Sim: ${{cl.centroid_sim.toFixed(3)}}</div>
        <div style="margin-top:6px">${{terms_html}}</div>
        <div class="op-detail" style="margin-top:4px;font-style:italic;color:var(--subtext)">"${{cl.sample}}"</div>
      </div>`;
  }});

  if ((nd.amplifiers && nd.amplifiers.length) || (nd.soldiers && nd.soldiers.length)) {{
    document.getElementById('semantic-roles-panel').style.display = 'block';
    const rl = document.getElementById('semantic-roles-list');
    if (nd.amplifiers && nd.amplifiers.length) {{
      rl.innerHTML += `<div style="margin:4px 0"><span style="color:var(--orange);font-weight:bold">AMPLIFIERS (${{nd.amplifiers.length}}):</span> <span style="color:var(--yellow)">${{nd.amplifiers.slice(0,15).join(' · ')}}</span></div>`;
    }}
    if (nd.soldiers && nd.soldiers.length) {{
      rl.innerHTML += `<div style="margin:4px 0"><span style="color:var(--red);font-weight:bold">SOLDIERS (${{nd.soldiers.length}}):</span> <span style="color:var(--yellow)">${{nd.soldiers.slice(0,15).join(' · ')}}</span></div>`;
    }}
  }}
}})();

// ── Legal Evidence Package ────────────────────────────────────────────────────
(function() {{
  const ld = DATA.legal;
  if (!ld || !ld.case_id) return;

  const box = document.getElementById('legal-summary-box');
  const cats = Object.entries(ld.categories || {{}}).map(([k,v]) => `<span class="badge badge-blue" style="margin:2px">${{k}}: ${{v}}</span>`).join('');
  const paths = (ld.html_path ? `<div style="margin-top:8px;font-size:10px;color:var(--cyan)">▸ HTML: ${{ld.html_path}}</div>` : '') +
                (ld.json_path ? `<div style="font-size:10px;color:var(--cyan)">▸ JSON: ${{ld.json_path}}</div>` : '');
  box.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:flex-start">
      <div>
        <div style="color:var(--green);font-weight:bold;font-size:14px">CASE: ${{ld.case_id}}</div>
        <div style="color:var(--subtext);font-size:10px;margin-top:2px">Generated: ${{ld.generated_at}}</div>
      </div>
      <div style="text-align:right">
        <div style="color:var(--yellow);font-weight:bold;font-size:18px">${{ld.total_items}}</div>
        <div style="color:var(--subtext);font-size:10px">EVIDENCE ITEMS</div>
      </div>
    </div>
    <div style="margin-top:10px">${{cats}}</div>
    <div style="margin-top:10px;font-size:10px;color:var(--subtext)">Manifest integrity hash (SHA-256):</div>
    <div style="font-size:9px;color:var(--green);word-break:break-all;margin-top:2px">${{ld.manifest_hash}}</div>
    <div style="margin-top:8px;color:var(--text);font-size:11px">${{ld.summary}}</div>
    ${{paths}}`;
}})();

// ── Account Lifecycle Anomaly ─────────────────────────────────────────────────
(function() {{
  const lc = DATA.lifecycle;
  if (!lc) return;

  document.getElementById('lifecycle-summary').textContent = lc.summary || '';

  // Sleeper cells
  if (lc.cells && lc.cells.length) {{
    document.getElementById('lifecycle-cells-panel').style.display = 'block';
    const cl = document.getElementById('lifecycle-cells-list');
    lc.cells.forEach(c => {{
      cl.innerHTML += `<div style="margin:4px 0;padding:6px;background:var(--surface);border-radius:6px;border-left:3px solid #cba6f7">
        <span style="color:#cba6f7;font-weight:bold">CELL-${{String(c.cell_id).padStart(2,'0')}}</span>
        <span style="color:var(--subtext);margin:0 8px">${{c.act_start}} – ${{c.act_end}}</span>
        <span style="color:var(--orange)">${{c.posts_hit}} post(s) hit</span>
        <span style="color:var(--subtext);margin-left:8px">coord=${{c.coord_score}}%</span>
        <div style="margin-top:3px;color:var(--yellow)">${{c.actors.join(' · ').substring(0,100)}}</div>
      </div>`;
    }});
  }}

  // Actor cards
  const grid = document.getElementById('lifecycle-actors-grid');
  const labelColors = {{ SLEEPER: '#f38ba8', BURST: '#fab387', COORDINATOR: '#f9e2af', ORGANIC: '#45475a' }};
  (lc.top_actors || []).forEach(a => {{
    const lc_clr = labelColors[a.label] || '#cdd6f4';
    const score_w = Math.min(a.score, 100);
    grid.innerHTML += `
      <div class="op-card" style="border-color:#280040">
        <h4 style="color:#cba6f7">${{a.actor.substring(0,30)}}</h4>
        <div class="conf-bar"><div class="conf-fill" style="width:${{score_w}}%;background:${{lc_clr}}"></div></div>
        <div class="op-detail" style="color:${{lc_clr}};font-weight:bold">${{a.label}} — ${{a.score}}/100</div>
        <div class="op-detail">First: ${{a.first_seen || '—'}} · Win: ${{a.window_h}}h · CPH: ${{a.cph}}</div>
        <div class="op-detail">Lag: ${{a.lag_h}}h · Burst: ${{a.burst}}</div>
        ${{(a.flags||[]).map(f=>`<span class="tag" style="background:#1a0028">${{f}}</span>`).join('')}}
      </div>`;
  }});

  if (!lc.top_actors || !lc.top_actors.length) {{
    grid.innerHTML = '<div style="color:var(--subtext);margin-top:20px;text-align:center">No lifecycle anomalies detected</div>';
  }}
}})();

// ── Narrative Injection Points ────────────────────────────────────────────────
(function() {{
  const id = DATA.injection;
  if (!id) return;

  document.getElementById('injection-summary').textContent = id.summary || '';

  // Top injectors
  const il = document.getElementById('injection-injectors-list');
  (id.top_injectors || []).forEach((inj, i) => {{
    const badge_clr = i === 0 ? '#f38ba8' : i < 3 ? '#fab387' : '#f9e2af';
    il.innerHTML += `<span style="background:var(--surface);border:1px solid ${{badge_clr}};padding:3px 8px;border-radius:12px;font-size:10px">
      <span style="color:${{badge_clr}};font-weight:bold">${{inj.actor.substring(0,25)}}</span>
      <span style="color:var(--subtext);margin-left:4px">×${{inj.count}}</span>
    </span>`;
  }});
  if (!id.top_injectors || !id.top_injectors.length) {{
    il.textContent = 'No injectors identified';
  }}

  // Narrative cards
  const ng = document.getElementById('injection-narratives-grid');
  (id.injections || []).forEach(inj => {{
    const scoreClr = inj.score >= 70 ? '#f38ba8' : inj.score >= 50 ? '#fab387' : '#f9e2af';
    const terms_html = (inj.terms || []).map(t => `<span class="tag">${{t}}</span>`).join('');
    ng.innerHTML += `
      <div class="op-card" style="border-color:#003050">
        <h4 style="color:var(--cyan)">${{inj.id}}</h4>
        <div style="margin:4px 0;font-size:10px">
          <span style="color:var(--yellow);font-weight:bold">${{inj.seed}}</span>
          ${{inj.seed_ts ? `<span style="color:var(--subtext);margin-left:6px">${{inj.seed_ts}}</span>` : ''}}
        </div>
        <div style="margin-top:6px">${{terms_html}}</div>
        <div class="conf-bar" style="margin-top:8px"><div class="conf-fill" style="width:${{inj.score}}%;background:${{scoreClr}}"></div></div>
        <div class="op-detail" style="color:${{scoreClr}}">Score: ${{inj.score}}/100 · Prop: ${{inj.prop_count}} comments · ${{inj.prop_posts}} posts</div>
        ${{inj.co_inj && inj.co_inj.length ? `<div class="op-detail" style="color:var(--subtext)">Co-inj: ${{inj.co_inj.join(', ')}}</div>` : ''}}
        <div style="font-style:italic;color:var(--subtext);font-size:9px;margin-top:4px">"${{(inj.seed_text||'').substring(0,80)}}"</div>
      </div>`;
  }});
  if (!id.injections || !id.injections.length) {{
    ng.innerHTML = '<div style="color:var(--subtext);margin-top:20px;text-align:center">No narrative injections detected</div>';
  }}

  // Propagation chains
  if (id.chains && id.chains.length) {{
    document.getElementById('injection-chains-panel').style.display = 'block';
    const ch = document.getElementById('injection-chains-list');
    id.chains.forEach(chain => {{
      ch.innerHTML += `<div style="margin:6px 0;padding:8px;background:var(--surface);border-radius:6px;border-left:3px solid var(--cyan)">
        <div style="color:var(--cyan);font-weight:bold;margin-bottom:4px">${{chain.id}}</div>
        ${{(chain.steps||[]).map((s,i)=>`
          <div style="padding:2px 0 2px 8px;border-left:1px solid var(--overlay);margin-left:4px;font-size:9px">
            <span style="color:var(--subtext)">${{s.ts ? s.ts.substring(0,16) : '—'}}</span>
            <span style="color:var(--yellow);margin:0 6px">${{(s.actor||'').substring(0,25)}}</span>
            <span style="color:var(--text)">"${{(s.text||'').substring(0,60)}}"</span>
          </div>`).join('')}}
      </div>`;
    }});
  }}
}})();

// ── Influence Topology Score ──────────────────────────────────────────────────
(function() {{
  const td = DATA.topology;
  if (!td) return;

  document.getElementById('topology-summary').textContent = td.summary || '';

  // Roles panel
  const rl = document.getElementById('topology-roles-list');
  if (td.command_chain && td.command_chain.length) {{
    rl.innerHTML += `<div style="margin:4px 0"><span style="color:var(--red);font-weight:bold">COMMAND (${{td.command_chain.length}}):</span> <span style="color:var(--yellow)">${{td.command_chain.join(' · ').substring(0,120)}}</span></div>`;
  }}
  if (td.amplifiers && td.amplifiers.length) {{
    rl.innerHTML += `<div style="margin:4px 0"><span style="color:var(--orange);font-weight:bold">AMPLIFIERS (${{td.amplifiers.length}}):</span> <span style="color:var(--yellow)">${{td.amplifiers.join(' · ').substring(0,120)}}</span></div>`;
  }}
  if (td.hubs && td.hubs.length) {{
    rl.innerHTML += `<div style="margin:4px 0"><span style="color:var(--cyan);font-weight:bold">HUBS (${{td.hubs.length}}):</span> <span style="color:var(--yellow)">${{td.hubs.join(' · ').substring(0,120)}}</span></div>`;
  }}
  const giniBar = Math.round(td.gini * 100);
  rl.innerHTML += `<div style="margin-top:10px;padding:8px;background:var(--surface);border-radius:6px">
    <div style="color:var(--subtext);font-size:10px">PAGERANK GINI CONCENTRATION</div>
    <div style="background:var(--overlay);border-radius:4px;height:8px;margin:4px 0">
      <div style="background:${{giniBar>=60?'#f38ba8':giniBar>=35?'#fab387':'#a6e3a1'}};width:${{giniBar}}%;height:100%;border-radius:4px"></div>
    </div>
    <div style="color:var(--subtext);font-size:10px">${{td.gini.toFixed(3)}} — ${{giniBar>=60?'HIGHLY CONCENTRATED':giniBar>=35?'MODERATE':'DISTRIBUTED'}}</div>
    <div style="margin-top:4px;font-size:10px"><span style="color:var(--yellow)">Topology score: ${{td.score}}/100</span> · <span style="color:var(--subtext)">CIB coord: ${{td.coord_score}}/100</span> · <span style="color:var(--orange)">Suspects in top: ${{td.suspect_top}}%</span></div>
  </div>`;

  // Communities panel
  const cl = document.getElementById('topology-comms-list');
  (td.communities || []).forEach(c => {{
    const sc = c.susp_ratio >= 0.5 ? '#f38ba8' : c.susp_ratio >= 0.3 ? '#fab387' : '#a6e3a1';
    cl.innerHTML += `<div style="padding:5px 0;border-bottom:1px solid var(--overlay)">
      <span style="color:var(--cyan);font-weight:bold">COMM-${{String(c.id).padStart(2,'0')}}</span>
      <span style="color:var(--subtext);margin:0 8px">size=${{c.size}}</span>
      <span style="color:var(--yellow)">${{c.top_actor.substring(0,25)}}</span>
      <span style="color:var(--subtext);margin:0 6px">·</span>
      <span style="color:var(--orange)">avg=${{c.avg_inf.toFixed(1)}}/100</span>
      <span style="color:${{sc}};margin-left:6px">suspects=${{Math.round(c.susp_ratio*100)}}%</span>
    </div>`;
  }});
  if (!td.communities || !td.communities.length) {{
    cl.innerHTML = '<div style="color:var(--subtext);margin-top:20px;text-align:center">No communities detected</div>';
  }}

  // Actor cards
  const grid = document.getElementById('topology-actors-grid');
  const roleColors = {{ COMMAND:'#f38ba8', AMPLIFIER:'#fab387', HUB:'#f9e2af', BOT_CLUSTER:'#cba6f7', PERIPHERAL:'#45475a' }};
  (td.actors || []).forEach(a => {{
    const rc   = roleColors[a.role] || '#cdd6f4';
    const sw   = Math.min(a.score, 100);
    const susp = a.suspect ? `<span style="background:#2a0010;color:#f38ba8;padding:1px 5px;border-radius:4px;font-size:9px">★ BOT ${{a.susp_score}}</span>` : '';
    grid.innerHTML += `
      <div class="op-card" style="border-color:#001A3A">
        <h4 style="color:var(--cyan)">#${{a.rank}} ${{a.actor.substring(0,28)}}</h4>
        <div class="conf-bar"><div class="conf-fill" style="width:${{sw}}%;background:${{rc}}"></div></div>
        <div class="op-detail" style="color:${{rc}};font-weight:bold">${{a.role}} — ${{a.score.toFixed(1)}}/100</div>
        <div class="op-detail">PR: ${{a.pagerank.toFixed(6)}} · BT: ${{a.betweenness.toFixed(4)}} · DEG: ${{a.degree}}</div>
        ${{susp}}
      </div>`;
  }});
  if (!td.actors || !td.actors.length) {{
    grid.innerHTML = '<div style="color:var(--subtext);margin-top:20px;text-align:center">No CIB topology data available</div>';
  }}
}})();

// ── Hashtag Weaponization ─────────────────────────────────────────────────────
(function() {{
  const hd = DATA.hashtag;
  if (!hd) return;

  document.getElementById('hashtag-summary').textContent = hd.summary || '';

  // Weaponized tag badges
  if (hd.weaponized && hd.weaponized.length) {{
    document.getElementById('hashtag-weaponized-panel').style.display = 'block';
    const tl = document.getElementById('hashtag-tags-list');
    hd.weaponized.forEach((tag, i) => {{
      const clr = i < 3 ? '#f38ba8' : i < 6 ? '#fab387' : '#f9e2af';
      tl.innerHTML += `<span style="background:var(--surface);border:1px solid ${{clr}};padding:3px 8px;border-radius:12px;font-size:10px;font-weight:bold;color:${{clr}}">${{tag}}</span>`;
    }});
  }}

  // Top seeders
  if (hd.top_seeders && hd.top_seeders.length) {{
    document.getElementById('hashtag-seeders-panel').style.display = 'block';
    const sl = document.getElementById('hashtag-seeders-list');
    hd.top_seeders.forEach((s, i) => {{
      const clr = i === 0 ? '#f38ba8' : i < 3 ? '#fab387' : '#f9e2af';
      sl.innerHTML += `<span style="background:var(--surface);border:1px solid ${{clr}};padding:2px 6px;border-radius:10px;font-size:10px;color:${{clr}}">${{s.substring(0,25)}}</span>`;
    }});
  }}

  // Profile cards
  const grid = document.getElementById('hashtag-profiles-grid');
  const labelColors = {{ RAPID_SEEDING: '#f38ba8', AMPLIFIED: '#fab387', ORGANIC: '#a6e3a1' }};
  (hd.profiles || []).forEach(p => {{
    const lc  = labelColors[p.label] || '#cdd6f4';
    const rw  = Math.min(p.rate * 20, 100);
    const seeders_html = (p.seeders||[]).map(s=>`<span class="tag">${{s.substring(0,18)}}</span>`).join('');
    const curve_pts = (p.curve||[]).slice(0,6).map(pt=>`${{pt.hour.substring(11,16)}}:${{pt.count}}`).join(' → ');
    grid.innerHTML += `
      <div class="op-card" style="border-color:${{p.weaponized?'#3d1000':'#1e1800'}}">
        <h4 style="color:var(--yellow)">${{p.tag}}</h4>
        <div class="conf-bar"><div class="conf-fill" style="width:${{rw}}%;background:${{lc}}"></div></div>
        <div class="op-detail" style="color:${{lc}};font-weight:bold">${{p.label}} — ${{p.rate.toFixed(1)}}x growth</div>
        <div class="op-detail">Uses: ${{p.uses}} · Actors: ${{p.actors}} · Posts: ${{p.posts}} · Peak/h: ${{p.peak}}</div>
        ${{seeders_html}}
        ${{curve_pts ? `<div class="op-detail" style="font-size:9px;margin-top:4px;color:var(--subtext)">${{curve_pts}}</div>` : ''}}
      </div>`;
  }});
  if (!hd.profiles || !hd.profiles.length) {{
    grid.innerHTML = '<div style="color:var(--subtext);margin-top:20px;text-align:center">No hashtags found in comments</div>';
  }}
}})();

// ── TrollHunter: Mexican Political CIB Detector ──────────────────────────────
let trollAllProfiles = [];
let currentTrollFilter = 'ALL';

function trollFilter(cls) {{
  currentTrollFilter = cls;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  const idMap = {{ ALL:'fb-all', CONFIRMED_BOT:'fb-bot', HIGH_RISK:'fb-hr', SUSPICIOUS:'fb-sus', LIKELY_HUMAN:'fb-lh' }};
  const btn = document.getElementById(idMap[cls]);
  if (btn) btn.classList.add('active');
  renderTrollProfiles();
}}

function renderTrollProfiles() {{
  const grid = document.getElementById('troll-profiles-grid');
  const filtered = currentTrollFilter === 'ALL'
    ? trollAllProfiles
    : trollAllProfiles.filter(p => p.class === currentTrollFilter);
  const classClr = {{
    CONFIRMED_BOT: '#f38ba8', HIGH_RISK: '#fab387',
    SUSPICIOUS: '#f9e2af', LIKELY_HUMAN: '#89b4fa', HUMAN: '#a6e3a1',
  }};
  const classIcon = {{
    CONFIRMED_BOT: '⛔', HIGH_RISK: '🔴', SUSPICIOUS: '🟡',
    LIKELY_HUMAN: '🔵', HUMAN: '🟢',
  }};
  const sevClr = {{ CRITICAL: '#f38ba8', HIGH: '#fab387', MEDIUM: '#f9e2af', LOW: '#cdd6f4' }};
  grid.innerHTML = '';
  if (!filtered.length) {{
    grid.innerHTML = '<div style="color:var(--subtext);margin-top:20px;text-align:center">No actors match this filter</div>';
    return;
  }}
  filtered.forEach(p => {{
    const lc  = classClr[p.class] || '#cdd6f4';
    const ic  = classIcon[p.class] || '⚪';
    const rw  = Math.min(p.score, 100);
    const sigs = (p.signals || []).map(s => {{
      const sc = sevClr[s.severity] || '#cdd6f4';
      return `<div style="border-left:2px solid ${{sc}};padding:3px 6px;margin-top:4px;font-size:9px">
        <span style="color:${{sc}};font-weight:bold">${{s.code}}</span>
        <span style="color:var(--subtext)"> — ${{s.label}}</span>
        <div style="color:var(--subtext);font-size:8px;margin-top:2px">${{s.detail.substring(0,180)}}${{s.detail.length>180?'…':''}}</div>
      </div>`;
    }}).join('');
    const samples = (p.sample || []).map(t => `<div style="color:var(--subtext);font-size:8px;font-style:italic;margin-top:2px">"${{t.substring(0,80)}}"</div>`).join('');
    grid.innerHTML += `
      <div class="op-card" style="border-color:${{p.score>=80?'#3d0000':p.score>=60?'#3d1500':p.score>=40?'#3d3000':'#103d20'}}">
        <div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:4px">
          <h4 style="color:var(--text);margin:0">${{ic}} ${{p.actor.substring(0,28)}}</h4>
          <span style="color:${{lc}};font-weight:bold;font-size:13px">${{p.score}}</span>
        </div>
        <div class="conf-bar"><div class="conf-fill" style="width:${{rw}}%;background:${{lc}}"></div></div>
        <div style="color:${{lc}};font-size:10px;font-weight:bold;margin-top:4px">${{p.class}}</div>
        <div class="op-detail">
          Comments: ${{p.comments}} · Posts attacked: ${{p.posts}} ·
          CPH: ${{p.cph.toFixed?p.cph.toFixed(1):'—'}} ·
          Attack ratio: ${{Math.round(p.attacks*100)}}%
        </div>
        ${{sigs}}
        ${{samples}}
      </div>`;
  }});
}}

(function() {{
  const td = DATA.troll;
  if (!td) return;

  document.getElementById('troll-summary').textContent = td.summary || '';

  // Stat badges
  const badges = document.getElementById('troll-badges');
  const badgeData = [
    {{ label: 'CONFIRMED BOT', val: (td.confirmed||[]).length, clr: '#f38ba8' }},
    {{ label: 'HIGH RISK',     val: (td.high_risk||[]).length, clr: '#fab387' }},
    {{ label: 'SUSPICIOUS',    val: (td.suspicious||[]).length, clr: '#f9e2af' }},
    {{ label: 'FOREIGN NAMES', val: (td.foreign_names||[]).length, clr: '#cba6f7' }},
    {{ label: 'PAGE ACCOUNTS', val: (td.page_operators||[]).length, clr: '#89dceb' }},
    {{ label: 'MULTI-PAGE OPS',val: (td.multi_page_ops||[]).length, clr: '#f38ba8' }},
  ];
  badgeData.forEach(b => {{
    if (b.val > 0) {{
      badges.innerHTML += `<span style="background:var(--surface);border:1px solid ${{b.clr}};
        padding:4px 10px;border-radius:12px;font-size:10px;font-weight:bold;color:${{b.clr}}">
        ${{b.val}} ${{b.label}}</span>`;
    }}
  }});

  trollAllProfiles = td.profiles || [];
  renderTrollProfiles();
}})();

// ── Account Velocity Profile ──────────────────────────────────────────────────
(function() {{
  const vd = DATA.velocity;
  if (!vd) return;

  document.getElementById('velocity-summary').textContent = vd.summary || '';

  const botList  = document.getElementById('velocity-bot-list');
  const suspList = document.getElementById('velocity-susp-list');
  (vd.bot_velocity || []).forEach((a, i) => {{
    const clr = i < 3 ? '#f38ba8' : '#fab387';
    botList.innerHTML += `<div style="padding:3px 0;border-bottom:1px solid var(--overlay);color:${{clr}}">🤖 ${{a.substring(0,30)}}</div>`;
  }});
  if (!vd.bot_velocity || !vd.bot_velocity.length) {{
    botList.innerHTML = '<div style="color:var(--subtext);margin-top:10px">No bot-velocity actors detected</div>';
  }}
  (vd.suspicious || []).forEach((a, i) => {{
    const clr = i < 3 ? '#fab387' : '#f9e2af';
    suspList.innerHTML += `<div style="padding:3px 0;border-bottom:1px solid var(--overlay);color:${{clr}}">⚠ ${{a.substring(0,30)}}</div>`;
  }});
  if (!vd.suspicious || !vd.suspicious.length) {{
    suspList.innerHTML = '<div style="color:var(--subtext);margin-top:10px">No suspicious-rate actors</div>';
  }}

  const grid = document.getElementById('velocity-actors-grid');
  const labelClr = {{ BOT_VELOCITY: '#f38ba8', SUSPICIOUS: '#fab387', HUMAN: '#a6e3a1' }};
  (vd.actors || []).forEach(a => {{
    const lc  = labelClr[a.label] || '#cdd6f4';
    const rw  = Math.min(a.score, 100);
    grid.innerHTML += `
      <div class="op-card" style="border-color:${{a.label==='BOT_VELOCITY'?'#3d1520':a.label==='SUSPICIOUS'?'#3d2010':'#103d20'}}">
        <h4 style="color:var(--cyan)">${{a.actor.substring(0,28)}}</h4>
        <div class="conf-bar"><div class="conf-fill" style="width:${{rw}}%;background:${{lc}}"></div></div>
        <div class="op-detail" style="color:${{lc}};font-weight:bold">${{a.label}} — CPH: ${{a.cph.toFixed(1)}}</div>
        <div class="op-detail">Comments: ${{a.comments}} · Posts: ${{a.posts}} · Span: ${{a.span_h.toFixed(1)}}h</div>
      </div>`;
  }});
  if (!vd.actors || !vd.actors.length) {{
    grid.innerHTML = '<div style="color:var(--subtext);margin-top:20px;text-align:center">No actor velocity data available</div>';
  }}
}})();

// ── Cross-Post Narrative Seeding ──────────────────────────────────────────────
(function() {{
  const sd = DATA.seeding;
  if (!sd) return;

  document.getElementById('seeding-summary').textContent = sd.summary || '';

  if (sd.cross_actors && sd.cross_actors.length) {{
    document.getElementById('seeding-cross-panel').style.display = 'block';
    const cl = document.getElementById('seeding-cross-list');
    sd.cross_actors.forEach((a, i) => {{
      const clr = i < 3 ? '#f38ba8' : i < 6 ? '#fab387' : '#f9e2af';
      cl.innerHTML += `<span style="background:var(--surface);border:1px solid ${{clr}};padding:3px 8px;border-radius:12px;font-size:10px;color:${{clr}}">${{a.substring(0,22)}}</span>`;
    }});
  }}

  const grid = document.getElementById('seeding-seeds-grid');
  (sd.seeds || []).forEach(s => {{
    const spreadClr = s.spread >= 3 ? '#f38ba8' : s.spread >= 2 ? '#fab387' : '#89b4fa';
    grid.innerHTML += `
      <div class="op-card" style="border-color:${{s.spread >= 3?'#3d1520':'#1e1800'}}">
        <h4 style="color:var(--yellow)">${{s.key.substring(0,50)}}…</h4>
        <div class="op-detail" style="color:var(--subtext);font-size:9px">${{s.text.substring(0,100)}}</div>
        <div class="op-detail" style="color:#f38ba8;font-weight:bold;margin-top:4px">
          Seed: ${{s.first}} ${{s.first_ts?'@ '+s.first_ts:''}}
        </div>
        <div class="op-detail" style="color:${{spreadClr}}">
          Spread: ${{s.spread}} more post(s) · Total posts: ${{s.posts}} · Actors: ${{s.actors}}
        </div>
      </div>`;
  }});
  if (!sd.seeds || !sd.seeds.length) {{
    grid.innerHTML = '<div style="color:var(--subtext);margin-top:20px;text-align:center">No cross-post seeding patterns detected</div>';
  }}
}})();

// ── Cross-Post Time Correlation ────────────────────────────────────────────────
(function() {{
  const cd = DATA.correlation;
  if (!cd) return;

  document.getElementById('correlation-summary').textContent = cd.summary || '';

  const highPairs = (cd.pairs || []).filter(p => p.label !== 'LOW');
  if (highPairs.length) {{
    document.getElementById('correlation-pairs-panel').style.display = 'block';
    const grid = document.getElementById('correlation-pairs-grid');
    highPairs.forEach(p => {{
      const jclr = p.jaccard >= 0.35 ? '#f38ba8' : '#fab387';
      const a_short = (p.a.split('/').pop() || p.a).substring(0,30);
      const b_short = (p.b.split('/').pop() || p.b).substring(0,30);
      grid.innerHTML += `
        <div class="op-card" style="border-color:${{p.label==='HIGH'?'#3d1520':'#3d2010'}}">
          <h4 style="color:var(--orange)">${{p.label}} — Jaccard ${{p.jaccard.toFixed(3)}}</h4>
          <div class="conf-bar"><div class="conf-fill" style="width:${{Math.min(p.jaccard*200,100)}}%;background:${{jclr}}"></div></div>
          <div class="op-detail" style="color:var(--subtext);font-size:9px">A: ${{a_short}}</div>
          <div class="op-detail" style="color:var(--subtext);font-size:9px">B: ${{b_short}}</div>
          <div class="op-detail" style="color:${{jclr}}">Shared actors: ${{p.shared}} / A:${{p.a_size}} B:${{p.b_size}}</div>
        </div>`;
    }});
  }}
}})();

// ── Bot Operator Attribution ───────────────────────────────────────────────────
(function() {{
  const ad = DATA.attribution;
  if (!ad) return;

  document.getElementById('attribution-summary').textContent = ad.summary || '';

  const grid = document.getElementById('attribution-operators-grid');
  const labelClr = {{ CONFIRMED: '#f38ba8', LIKELY: '#fab387', POSSIBLE: '#f9e2af' }};
  (ad.operators || []).forEach(op => {{
    const lc   = labelClr[op.label] || '#cdd6f4';
    const rw   = Math.min(op.conf, 100);
    const bots = (op.bots || []).slice(0,4).map(b=>`<span class="tag">${{b.substring(0,18)}}</span>`).join('');
    grid.innerHTML += `
      <div class="op-card" style="border-color:${{op.label==='CONFIRMED'?'#3d1520':op.label==='LIKELY'?'#3d2010':'#3d3010'}}">
        <h4 style="color:var(--purple)">${{op.operator.substring(0,28)}}</h4>
        <div class="conf-bar"><div class="conf-fill" style="width:${{rw}}%;background:${{lc}}"></div></div>
        <div class="op-detail" style="color:${{lc}};font-weight:bold">${{op.label}} — Confidence ${{op.conf}}%</div>
        <div class="op-detail">Attributed bots: ${{op.bots ? op.bots.length : 0}} · Co-posts: ${{op.co_posts}} · Excl: ${{(op.excl*100).toFixed(0)}}%</div>
        ${{bots}}
      </div>`;
  }});
  if (!ad.operators || !ad.operators.length) {{
    grid.innerHTML = '<div style="color:var(--subtext);margin-top:20px;text-align:center">No operator attribution patterns above threshold</div>';
  }}
}})();

// ── Sortable table ────────────────────────────────────────────────────────────
let sortDir = {{}};
function sortTable(col) {{
  const tbody = document.getElementById('suspects-tbody');
  const rows  = Array.from(tbody.querySelectorAll('tr'));
  sortDir[col] = !sortDir[col];
  rows.sort((a, b) => {{
    const va = a.cells[col]?.textContent.trim() || '';
    const vb = b.cells[col]?.textContent.trim() || '';
    const na = parseFloat(va), nb = parseFloat(vb);
    const cmp = isNaN(na) ? va.localeCompare(vb) : na - nb;
    return sortDir[col] ? cmp : -cmp;
  }});
  rows.forEach(r => tbody.appendChild(r));
}}

// ── E1: Identity Persistence Tracker ─────────────────────────────────────────
(function() {{
  const id = DATA.identity;
  if (!id) return;
  const confColor = {{CONFIRMED_MORPH:'#f38ba8',PROBABLE_MORPH:'#fab387',POSSIBLE_MORPH:'#f9e2af'}};
  const FP_LABELS = ['vocab','len','caps','emoji','punct','attack','digit','rhythm'];

  const summary = document.getElementById('identity-summary');
  if (summary) summary.textContent = id.summary;

  const stats = document.getElementById('identity-stats');
  if (stats) {{
    [
      ['FINGERPRINTED', id.total, 'cyan'],
      ['UNIQUE OPERATORS', id.unique, 'blue'],
      ['CONFIRMED MORPHS', (id.confirmed||[]).length, 'red'],
      ['PROBABLE MORPHS',  (id.probable||[]).length,  'orange'],
    ].forEach(([l,v,c]) => {{
      stats.innerHTML += `<div style="background:var(--surface);border-radius:6px;padding:8px 12px;text-align:center">
        <div class="value ${{c}}" style="font-size:18px">${{v}}</div>
        <div class="label" style="font-size:9px">${{l}}</div>
      </div>`;
    }});
  }}

  const grid = document.getElementById('identity-morphs-grid');
  if (!grid || !id.morphs) return;
  id.morphs.forEach(m => {{
    const col = confColor[m.conf] || '#888';
    const fp_a = (m.fp_a||[]).map((v,i) => `${{FP_LABELS[i]||i}}:${{v.toFixed(2)}}`).join(' ');
    const fp_b = (m.fp_b||[]).map((v,i) => `${{FP_LABELS[i]||i}}:${{v.toFixed(2)}}`).join(' ');
    grid.innerHTML += `
      <div class="op-card" style="border-left:3px solid ${{col}}">
        <div style="font-weight:bold;color:${{col}};font-size:10px">${{m.conf}}</div>
        <div style="color:var(--orange);font-size:13px;font-weight:bold;margin:3px 0">
          sim ${{m.sim.toFixed(3)}}
        </div>
        <div style="color:var(--text);font-size:10px">
          <b>NOW:</b> ${{m.actor_a}} <span style="color:var(--subtext)">(${{m.camp_a}})</span>
        </div>
        <div style="color:var(--text);font-size:10px">
          <b>WAS:</b> ${{m.actor_b}} <span style="color:var(--subtext)">(${{m.camp_b}})</span>
        </div>
        <div style="color:var(--overlay);font-size:8px;margin-top:4px;font-family:monospace">
          A: ${{fp_a}}<br>B: ${{fp_b}}
        </div>
      </div>`;
  }});
}})();

// ── E8: Narrative Mutation Tracker ────────────────────────────────────────────
(function() {{
  const mut = DATA.mutation;
  if (!mut) return;
  const typeColor = {{PIVOT:'#f38ba8',INJECTION:'#cba6f7',EXPANSION:'#fab387',AMPLIFICATION:'#f9e2af',CONVERGENCE:'#89b4fa'}};

  const summary = document.getElementById('mutation-summary');
  if (summary) summary.textContent = mut.summary;

  const badges = document.getElementById('mutation-type-badges');
  if (badges) {{
    [['PIVOT',mut.pivot,'#f38ba8'],['EXPANSION',mut.exp,'#fab387'],['INJECTION',mut.inj,'#cba6f7']].forEach(([l,v,c]) => {{
      if (v > 0) badges.innerHTML += `<span style="background:${{c}}22;color:${{c}};border:1px solid ${{c}};border-radius:4px;padding:2px 8px;font-size:10px">${{l}}: ${{v}}</span>`;
    }});
    if (mut.mutator) badges.innerHTML += `<span style="background:#31324422;color:#cba6f7;border:1px solid #cba6f7;border-radius:4px;padding:2px 8px;font-size:10px">TOP MUTATOR: ${{mut.mutator}}</span>`;
  }}

  // Intensity over time chart
  const ctx = document.getElementById('mutation-intensity-chart');
  if (ctx && mut.snapshots && mut.snapshots.length && typeof Chart !== 'undefined') {{
    const labels  = mut.snapshots.map(s => s.start.slice(11,16));
    const intens  = mut.snapshots.map(s => Math.min(100, Math.round(s.intensity * 200)));
    new Chart(ctx, {{
      type: 'line',
      data: {{
        labels,
        datasets: [{{
          label: 'Narrative intensity',
          data: intens,
          borderColor: '#f38ba8',
          backgroundColor: '#f38ba820',
          fill: true,
          tension: 0.4,
          pointRadius: 3,
        }}]
      }},
      options: {{
        responsive:true, maintainAspectRatio:false,
        plugins:{{ legend:{{display:false}} }},
        scales:{{
          x:{{ticks:{{color:'#6c7086',font:{{size:8}}}},grid:{{color:'#313244'}}}},
          y:{{ticks:{{color:'#6c7086'}},grid:{{color:'#313244'}},max:100}}
        }}
      }}
    }});
  }}

  const grid = document.getElementById('mutation-events-grid');
  if (!grid || !mut.mutations) return;
  mut.mutations.forEach(m => {{
    const col = typeColor[m.type] || '#888';
    grid.innerHTML += `
      <div class="op-card" style="border-left:3px solid ${{col}}">
        <div style="font-weight:bold;color:${{col}};font-size:11px">${{m.type}} <span style="font-weight:normal;color:var(--subtext)">score ${{m.score}}/100</span></div>
        <div style="color:var(--subtext);font-size:9px;margin:2px 0">${{m.from_ts}} → ${{m.to_ts}} · drop ${{m.drop.toFixed(2)}}</div>
        ${{m.new.length ? `<div style="color:var(--yellow);font-size:9px">+ ${{m.new.join(' · ')}}</div>` : ''}}
        ${{m.dropped.length ? `<div style="color:var(--overlay);font-size:9px">- ${{m.dropped.join(' · ')}}</div>` : ''}}
        <div style="color:var(--red);font-size:9px;margin-top:2px">introducer: <b>${{m.intro}}</b> → ${{m.adoption}} adopted</div>
      </div>`;
  }});
}})();

// ── E5: Dark Amplification Tracker ───────────────────────────────────────────
(function() {{
  const da = DATA.dark_amp;
  if (!da) return;
  const clsColor = {{DARK_AMP:'#f38ba8',SUSPICIOUS:'#f9e2af',VIRAL_GENUINE:'#89b4fa',ORGANIC:'#6c7086'}};
  const summary = document.getElementById('darkamp-summary');
  if (summary) summary.textContent = da.summary;
  const grid = document.getElementById('darkamp-events-grid');
  if (!grid || !da.events) return;
  da.events.filter(e => e.class !== 'ORGANIC').forEach(e => {{
    const col = clsColor[e.class] || '#888';
    grid.innerHTML += `
      <div class="op-card" style="border-left:3px solid ${{col}}">
        <div style="font-weight:bold;color:${{col}};font-size:10px">${{e.class}}</div>
        <div style="color:var(--text);font-size:11px;margin:2px 0">${{e.source}}</div>
        <div style="color:var(--orange);font-size:13px;font-weight:bold">${{e.factor.toFixed(1)}}x <span style="font-size:10px;color:var(--subtext)">above baseline</span></div>
        <div style="color:var(--subtext);font-size:9px">${{e.vel.toFixed(0)}} eng/h · age ${{e.age.toFixed(1)}}h · purity ${{(e.purity*100).toFixed(0)}}%</div>
        <div style="color:var(--overlay);font-size:9px;font-style:italic;margin-top:3px">${{e.preview}}</div>
      </div>`;
  }});
}})();

// ── E7: Bot Farm Shift Detector ───────────────────────────────────────────────
(function() {{
  const sh = DATA.shift;
  if (!sh) return;
  const confColor = {{HIGH:'#f38ba8',MEDIUM:'#fab387',LOW:'#f9e2af'}};
  const summary = document.getElementById('shift-summary');
  if (summary) summary.textContent = sh.summary;

  // Timeline chart: bot density per window
  const ctx = document.getElementById('shift-timeline-chart');
  if (ctx && sh.cohorts && sh.cohorts.length && typeof Chart !== 'undefined') {{
    const labels = sh.cohorts.map(c => c.start.slice(11,16));
    const botPcts = sh.cohorts.map(c => Math.round(c.pct * 100));
    const bgs = botPcts.map(p => p >= 60 ? '#f38ba8' : p >= 40 ? '#fab387' : '#a6e3a1');
    new Chart(ctx, {{
      type: 'bar',
      data: {{
        labels,
        datasets: [{{
          label: 'Bot density %',
          data: botPcts,
          backgroundColor: bgs,
          borderWidth: 0,
        }}]
      }},
      options: {{
        responsive:true, maintainAspectRatio:false,
        plugins:{{ legend:{{display:false}} }},
        scales:{{
          x:{{ticks:{{color:'#6c7086',font:{{size:8}}}}, grid:{{color:'#313244'}}}},
          y:{{ticks:{{color:'#6c7086'}}, grid:{{color:'#313244'}}, max:100, title:{{display:true,text:'Bot %',color:'#6c7086'}}}}
        }}
      }}
    }});
  }}

  const grid = document.getElementById('shift-events-grid');
  if (!grid || !sh.shifts) return;
  sh.shifts.forEach(s => {{
    const col = confColor[s.conf] || '#888';
    grid.innerHTML += `
      <div class="op-card" style="border-left:3px solid ${{col}}">
        <div style="font-weight:bold;color:${{col}};font-size:11px">${{s.conf}} SHIFT — score ${{s.score}}/100</div>
        <div style="color:var(--subtext);font-size:9px;margin:3px 0">
          ${{s.from}} → ${{s.to}}<br>
          jaccard ${{s.jaccard.toFixed(2)}} · turnover ${{(s.turnover*100).toFixed(0)}}% · naming sim ${{(s.sim*100).toFixed(0)}}%
        </div>
        ${{s.from_patterns.length ? `<div style="color:var(--overlay);font-size:8px">OLD: ${{s.from_patterns.join(' · ')}}</div>` : ''}}
        ${{s.to_patterns.length   ? `<div style="color:var(--overlay);font-size:8px">NEW: ${{s.to_patterns.join(' · ')}}</div>` : ''}}
      </div>`;
  }});
}})();

// ── E2: Reply-Chain Hijack Detector ─────────────────────────────────────────
(function() {{
  const rc = DATA.reply_chain;
  if (!rc) return;
  const typeColor = {{TEMPORAL:'#fab387',MENTION:'#cba6f7',SATURATION:'#f38ba8'}};
  const summary = document.getElementById('reply-summary');
  if (summary) summary.textContent = rc.summary;
  const career = document.getElementById('reply-career');
  if (career && rc.career && rc.career.length) {{
    career.innerHTML = `<span style="color:var(--red);font-size:11px;font-weight:bold">⛔ CAREER HIJACKERS: </span>` +
      rc.career.map(a => `<span style="background:#3d1520;color:#f38ba8;border-radius:3px;padding:1px 6px;font-size:10px;margin:2px">${{a}}</span>`).join(' ');
  }}
  const grid = document.getElementById('reply-posts-grid');
  if (!grid || !rc.posts) return;
  rc.posts.filter(p => p.score >= 30).forEach(p => {{
    const col = typeColor[p.type] || '#888';
    let targetsHtml = (p.targets||[]).map(t => `
      <div style="background:#1e1e2e;border-radius:4px;padding:6px;margin-top:4px">
        <div style="color:var(--yellow);font-size:9px">🎯 <b>${{t.author}}</b> (${{'❤'.repeat(Math.min(t.likes,5))}} ${{t.likes}} likes)</div>
        <div style="color:var(--overlay);font-size:8px;font-style:italic">"${{t.text}}"</div>
        <div style="color:${{typeColor[t.type]||'#888'}};font-size:9px">
          ${{t.type}} · ${{t.count}} bot replies · Δ${{t.delta.toFixed(0)}}s · intensity ${{t.score}}/100
        </div>
        <div style="color:var(--subtext);font-size:8px">${{t.bots.join(' · ')}}</div>
      </div>`).join('');
    grid.innerHTML += `
      <div class="op-card" style="border-left:3px solid ${{col}}">
        <div style="color:var(--text);font-weight:bold;font-size:10px">${{p.source}}</div>
        <div style="color:${{col}};font-size:11px;font-weight:bold;margin:2px 0">${{p.type}} — score ${{p.score}}/100</div>
        <div style="color:var(--subtext);font-size:9px">organic:${{p.organic}} bots:${{p.bots}} saturation:${{(p.sat*100).toFixed(0)}}%</div>
        ${{targetsHtml}}
      </div>`;
  }});
}})();

// ── E6: Cross-Campaign Actor Persistence ─────────────────────────────────────
(function() {{
  const cc = DATA.cross_campaign;
  if (!cc) return;
  const clsColor = {{PROFESSIONAL:'#f38ba8',PERSISTENT:'#fab387',RECURRING:'#f9e2af',NEW:'#6c7086'}};
  const summary = document.getElementById('cross-summary');
  if (summary) summary.textContent = cc.summary;
  const stats = document.getElementById('cross-stats');
  if (stats) {{
    [
      ['TOTAL TRACKED', cc.total, 'cyan'],
      ['CAMPAIGNS', cc.campaigns, 'blue'],
      ['PROFESSIONAL', (cc.pro||[]).length, 'red'],
      ['PERSISTENT', (cc.per||[]).length, 'orange'],
      ['RECURRING', (cc.recurring||[]).length, 'yellow'],
      ['NEW THIS SESSION', cc.new||0, 'green'],
    ].forEach(([l,v,c]) => {{
      stats.innerHTML += `<div style="background:var(--surface);border-radius:6px;padding:8px 12px;text-align:center">
        <div class="value ${{c}}" style="font-size:18px">${{v}}</div>
        <div class="label" style="font-size:9px">${{l}}</div>
      </div>`;
    }});
  }}
  const grid = document.getElementById('cross-actors-grid');
  if (!grid || !cc.actors) return;
  cc.actors.forEach(a => {{
    const col = clsColor[a.class] || '#888';
    grid.innerHTML += `
      <div class="op-card" style="border-left:3px solid ${{col}}">
        <div style="font-weight:bold;color:${{col}};font-size:10px">${{a.class}}</div>
        <div style="color:var(--text);font-size:11px;margin:2px 0">${{a.name}}</div>
        <div style="color:var(--orange);font-size:11px;font-weight:bold">${{a.camps}} campaign(s)</div>
        <div style="color:var(--subtext);font-size:9px">avg score ${{a.avg_score.toFixed(0)}}/100 · ${{a.total_c}} comments</div>
        <div style="color:var(--overlay);font-size:8px;margin-top:3px">${{(a.campaigns||[]).join(' → ')}}</div>
        ${{a.signals&&a.signals.length?`<div style="color:var(--yellow);font-size:8px;margin-top:2px">signals: ${{a.signals.join(' · ')}}</div>`:''}}
      </div>`;
  }});
}})();

// ── E4: Engagement Anomaly Index ─────────────────────────────────────────────
(function() {{
  const eng = DATA.engagement;
  if (!eng || !eng.total) return;
  const clsColor = {{
    BOT_BOOSTED:'#f38ba8', GHOST:'#fab387', SUSPICIOUS:'#f9e2af',
    AMPLIFIED:'#89b4fa', ORGANIC:'#6c7086'
  }};
  const summary = document.getElementById('engagement-summary');
  if (summary) summary.textContent = eng.summary;
  const grid = document.getElementById('engagement-posts-grid');
  if (!grid || !eng.posts) return;
  eng.posts.forEach(p => {{
    const col = clsColor[p.class] || '#888';
    grid.innerHTML += `
      <div class="op-card" style="border-left:3px solid ${{col}}">
        <div style="font-weight:bold;color:${{col}};font-size:11px">${{p.class}}</div>
        <div style="color:var(--text);font-size:10px;margin:2px 0">${{p.source}}</div>
        <div style="color:var(--orange);font-size:11px;font-weight:bold">${{p.ratio.toFixed(1)}}x ratio <span style="color:var(--subtext);font-size:10px">(${{p.dev > 0 ? '+' : ''}}${{p.dev.toFixed(0)}}%)</span></div>
        <div style="color:var(--subtext);font-size:9px">R:${{p.r}} C:${{p.c}} S:${{p.s}} · score ${{p.score}}/100</div>
        <div style="color:var(--overlay);font-size:9px;margin-top:4px">${{p.preview}}</div>
      </div>`;
  }});
}})();

// ── E3: Emotional Contagion Score ─────────────────────────────────────────────
(function() {{
  const cont = DATA.contagion;
  if (!cont) return;
  const dirColor = {{NEGATIVE:'#f38ba8',POSITIVE:'#a6e3a1',MIXED:'#f9e2af',NONE:'#6c7086'}};
  const summary = document.getElementById('contagion-summary');
  if (summary) summary.textContent = cont.summary;
  const dirEl = document.getElementById('contagion-direction');
  if (dirEl) {{
    dirEl.textContent = cont.direction;
    dirEl.style.color = dirColor[cont.direction] || '#888';
  }}
  // Build PRE/DURING/POST bar chart
  const ctx = document.getElementById('contagion-chart');
  if (ctx && typeof Chart !== 'undefined') {{
    const labels = ['PRE-BOT','DURING','POST-BOT'];
    const pre  = cont.pre  || {{}};
    const dur  = cont.during || {{}};
    const pst  = cont.post  || {{}};
    new Chart(ctx, {{
      type: 'bar',
      data: {{
        labels,
        datasets: [
          {{ label: 'NEG',  data: [pre.neg||0, dur.neg||0, pst.neg||0],  backgroundColor: '#f38ba8' }},
          {{ label: 'AGG',  data: [pre.agg||0, dur.agg||0, pst.agg||0],  backgroundColor: '#fab387' }},
          {{ label: 'POS',  data: [pre.pos||0, dur.pos||0, pst.pos||0],  backgroundColor: '#a6e3a1' }},
          {{ label: 'NEU',  data: [pre.neutral||0, dur.neutral||0, pst.neutral||0], backgroundColor: '#6c7086' }},
        ]
      }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ labels: {{ color: '#cdd6f4' }} }} }},
        scales: {{
          x: {{ ticks: {{ color:'#6c7086' }}, grid: {{ color:'#313244' }} }},
          y: {{ ticks: {{ color:'#6c7086' }}, grid: {{ color:'#313244' }}, max: 1.0 }}
        }}
      }}
    }});
  }}
  // Render affected posts
  const grid = document.getElementById('contagion-posts-grid');
  if (!grid || !cont.posts) return;
  cont.posts.filter(p => p.confirmed).forEach(p => {{
    const shift = p.shift;
    const shiftColor = shift > 0.2 ? '#f38ba8' : shift > 0 ? '#fab387' : '#a6e3a1';
    const windows = [p.pre, p.during, p.post].filter(Boolean)
      .map(w => `<span style="color:var(--subtext)">${{w.label.replace('_BOT','')}}:</span> ${{w.dominant}}(${{w.n}})`).join(' → ');
    grid.innerHTML += `
      <div class="op-card" style="border-left:3px solid ${{shiftColor}}">
        <div style="font-weight:bold;color:var(--text);font-size:10px">${{p.source}}</div>
        <div style="color:${{shiftColor}};font-size:12px;font-weight:bold;margin:2px 0">shift ${{shift > 0 ? '+' : ''}}${{shift.toFixed(3)}}</div>
        <div style="color:var(--subtext);font-size:9px">${{windows}}</div>
        ${{p.peak_agg ? `<div style="color:var(--overlay);font-size:9px;font-style:italic;margin-top:4px">"${{p.peak_agg}}"</div>` : ''}}
      </div>`;
  }});
}})();
  // ── RENDER CIB HERO SCORE ───────────────────────────────────────────────────
  (function renderCIBHero() {{
    const cs = D.cib_score;
    if (!cs) return;

    const score   = cs.score   || 0;
    const label   = cs.label   || 'ORGANIC';
    const quality = cs.data_quality || 'INSUFFICIENT';
    const nActive = cs.engines_active  || 0;
    const nPresent= cs.engines_present || 0;

    const labelMap = {{
      CONFIRMED_CIB:   {{ color: '#f38ba8', bg: '#3d1520', text: 'CONFIRMED CIB'   }},
      HIGH_CONFIDENCE: {{ color: '#fab387', bg: '#3d2010', text: 'HIGH CONFIDENCE' }},
      PROBABLE:        {{ color: '#f9e2af', bg: '#3d3010', text: 'PROBABLE CIB'    }},
      POSSIBLE:        {{ color: '#89b4fa', bg: '#10203d', text: 'POSSIBLE CIB'    }},
      ORGANIC:         {{ color: '#a6e3a1', bg: '#103d20', text: 'ORGANIC'         }},
    }};
    const qualityMap = {{
      SUFFICIENT:   {{ badge: 'HIGH DATA QUALITY',    color: '#a6e3a1' }},
      LOW:          {{ badge: 'LOW DATA QUALITY',     color: '#f9e2af' }},
      INSUFFICIENT: {{ badge: 'INSUFFICIENT DATA',    color: '#6c7086' }},
    }};
    const lm = labelMap[label] || labelMap.ORGANIC;
    const qm = qualityMap[quality] || qualityMap.INSUFFICIENT;

    // Gauge arc
    const arc = document.getElementById('cib-gauge-arc');
    if (arc) {{
      const circumference = 2 * Math.PI * 65;
      const filled = quality === 'INSUFFICIENT' ? 0 : score;
      const offset = circumference - (filled / 100) * circumference;
      setTimeout(() => {{
        arc.style.strokeDashoffset = offset;
        arc.style.stroke = quality === 'INSUFFICIENT' ? '#45475a' : lm.color;
      }}, 120);
    }}

    // Score number
    const scoreEl = document.getElementById('cib-gauge-score');
    if (scoreEl) {{
      if (quality === 'INSUFFICIENT') {{
        scoreEl.textContent = '—';
        scoreEl.style.color = '#45475a';
        scoreEl.style.fontSize = '28px';
      }} else {{
        scoreEl.textContent = score.toFixed(0);
        scoreEl.style.color = lm.color;
        scoreEl.style.fontSize = '42px';
      }}
    }}

    // Label badge
    const labelEl = document.getElementById('cib-gauge-label');
    if (labelEl) {{
      labelEl.textContent      = lm.text;
      labelEl.style.background = lm.bg;
      labelEl.style.color      = lm.color;
    }}

    // Engines counter with quality badge
    const engEl = document.getElementById('cib-engines-count');
    if (engEl) {{
      if (quality === 'INSUFFICIENT') {{
        engEl.innerHTML = `<span style="color:#f38ba8">⚠ ${{nPresent}} engines ran · 0 active signals</span>`;
      }} else {{
        engEl.innerHTML =
          `<span style="color:${{qm.color}}">${{qm.badge}}</span>` +
          `<br><span style="color:#6c7086">${{nActive}} active / ${{nPresent}} engines</span>`;
      }}
    }}

    // Narrative — ALWAYS set (never leave the template placeholder)
    const narr = document.getElementById('cib-narrative');
    if (narr) {{
      narr.textContent = cs.narrative ||
        (quality === 'INSUFFICIENT'
          ? 'No comment data available. Re-run with --comments-on-top N to enable full CIB analysis.'
          : 'No coordinated inauthentic behavior detected.');
      narr.style.color = quality === 'INSUFFICIENT' ? '#6c7086' : '#a6adc8';
      narr.style.fontStyle = 'normal';
    }}

    // Signals list
    const sigList = document.getElementById('cib-signals-list');
    if (sigList) {{
      if (cs.top_signals && cs.top_signals.length) {{
        cs.top_signals.slice(0, 4).forEach(sig => {{
          const el = document.createElement('div');
          el.className = 'cib-signal-item';
          el.style.borderLeftColor = lm.color;
          el.innerHTML = `<span class="sig-bullet" style="color:${{lm.color}}">&#9658;</span> ${{sig}}`;
          sigList.appendChild(el);
        }});
      }} else if (quality === 'INSUFFICIENT') {{
        const el = document.createElement('div');
        el.className = 'cib-signal-item';
        el.style.color = '#6c7086';
        el.innerHTML = '⚠ Run with <code>--comments-on-top 50</code> to load comment data for CIB analysis.';
        sigList.appendChild(el);
      }} else {{
        const el = document.createElement('div');
        el.className = 'cib-signal-item';
        el.style.color = '#6c7086';
        el.textContent = 'No significant inauthentic signals detected — activity appears organic.';
        sigList.appendChild(el);
      }}
    }}

    // Dimension bars: show all engines, dim those with score = 0
    const dimsPanel = document.getElementById('cib-dims-panel');
    if (dimsPanel && cs.dimensions && cs.dimensions.length) {{
      cs.dimensions.forEach(d => {{
        const hasSignal = d.score > 0;
        const barColor  = hasSignal
          ? (d.score >= 80 ? '#f38ba8' : d.score >= 60 ? '#fab387' : d.score >= 40 ? '#f9e2af' : '#89b4fa')
          : '#313244';
        const textColor = hasSignal ? barColor : '#45475a';
        const barWidth  = hasSignal ? d.score  : 0;
        const row = document.createElement('div');
        row.className = 'cib-dim-row';
        row.innerHTML = `
          <div class="cib-dim-label" style="color:${{textColor}}">${{d.label}}</div>
          <div class="cib-dim-bar-bg">
            <div class="cib-dim-bar" style="width:${{barWidth}}%;background:${{barColor}}"></div>
          </div>
          <div class="cib-dim-val" style="color:${{textColor}}">${{hasSignal ? d.score.toFixed(0) : '—'}}</div>`;
        dimsPanel.appendChild(row);
      }});
    }}
  }})();

  // ── RENDER MULTI-SOURCE MATRIX ───────────────────────────────────────────────
  (function renderMultiSource() {{
    const ms = D.multi_source;
    if (!ms || !ms.sources || ms.sources.length < 2) return;

    document.getElementById('multi-source-section').style.display = 'block';

    const summEl  = document.getElementById('ms-summary-text');
    const scoreEl = document.getElementById('ms-score-pill');
    if (summEl)  summEl.textContent = ms.summary;
    if (scoreEl) {{
      const sc = ms.score;
      const col = sc >= 70 ? '#f38ba8' : sc >= 40 ? '#fab387' : '#a6adc8';
      scoreEl.textContent = `Score: ${{sc.toFixed(0)}}/100`;
      scoreEl.style.color = col; scoreEl.style.borderColor = col;
    }}

    // Page pairs matrix
    const pairGrid = document.getElementById('ms-pair-grid');
    if (pairGrid && ms.page_pairs) {{
      const coordColors = {{
        HIGHLY_COORDINATED: '#f38ba8', COORDINATED: '#fab387',
        MODERATE: '#f9e2af', INDEPENDENT: '#6c7086',
      }};
      ms.page_pairs.forEach(p => {{
        const col = coordColors[p.label] || '#6c7086';
        const pct = (p.jaccard * 100).toFixed(0);
        pairGrid.innerHTML += `
          <div class="ms-pair-card">
            <h4 style="color:${{col}}">${{p.page_a}} ↔ ${{p.page_b}}</h4>
            <div style="color:${{col}};font-size:12px;font-weight:bold">${{p.label.replace('_',' ')}}</div>
            <div class="ms-overlap-bar">
              <div class="ms-overlap-fill" style="width:${{pct}}%;background:${{col}}"></div>
            </div>
            <div style="font-size:10px;color:var(--subtext)">
              ${{p.shared}} actores compartidos · Jaccard ${{pct}}%
            </div>
            <div class="ms-actor-tags">
              ${{(p.actors||[]).slice(0,5).map(a => `<span class="tag">${{a}}</span>`).join('')}}
            </div>
          </div>`;
      }});
    }}

    // Cross actors table
    if (ms.cross_actors && ms.cross_actors.length) {{
      const panel = document.getElementById('ms-cross-actors-panel');
      if (panel) panel.style.display = 'block';
      const tbody = document.getElementById('ms-cross-tbody');
      const riskColors = {{ CONFIRMED_CROSS:'#f38ba8', HIGH:'#fab387', MEDIUM:'#f9e2af', LOW:'#6c7086' }};
      ms.cross_actors.forEach(a => {{
        const rc = riskColors[a.risk] || '#6c7086';
        tbody.innerHTML += `<tr>
          <td style="font-weight:bold">${{a.name}}</td>
          <td><span style="color:var(--cyan);font-size:13px;font-weight:bold">${{a.page_count}}</span></td>
          <td><span class="badge" style="background:${{rc}}22;color:${{rc}}">${{a.risk.replace('_',' ')}}</span></td>
          <td><span style="color:${{a.bot_score>=60?'var(--red)':a.bot_score>=40?'var(--orange)':'var(--subtext)'}}">${{a.bot_score.toFixed(0)}}</span></td>
          <td style="color:var(--subtext);font-size:10px">${{a.pages.join(', ')}}</td>
        </tr>`;
      }});
    }}

    // Sync terms
    if (ms.sync_terms && ms.sync_terms.length) {{
      const tPanel = document.getElementById('ms-sync-terms-panel');
      if (tPanel) tPanel.style.display = 'block';
      const tList = document.getElementById('ms-sync-terms-list');
      ms.sync_terms.forEach(t => {{ tList.innerHTML += `<span class="ms-term">${{t}}</span>`; }});
    }}
  }})();

  // ── RENDER CONFIDENCE CHAINS ─────────────────────────────────────────────────
  (function renderChains() {{
    const chains = D.chains;
    if (!chains || !chains.length) return;

    document.getElementById('chain-section').style.display = 'block';
    const container = document.getElementById('chain-cards-container');

    const clsColors = {{
      CONFIRMED_BOT: {{ color: '#f38ba8', bg: '#3d1520', border: '#f38ba8' }},
      HIGH_RISK:     {{ color: '#fab387', bg: '#3d2010', border: '#fab387' }},
      SUSPICIOUS:    {{ color: '#f9e2af', bg: '#3d3010', border: '#f9e2af' }},
      LIKELY_HUMAN:  {{ color: '#89b4fa', bg: '#10203d', border: '#89b4fa' }},
      HUMAN:         {{ color: '#6c7086', bg: '#1e1e2e', border: '#6c7086' }},
    }};
    const sevColors = {{
      'CRÍTICO': '#f38ba8', 'ALTO': '#fab387', 'MEDIO': '#f9e2af', 'BAJO': '#89b4fa',
    }};

    chains.forEach((ch, idx) => {{
      const cc = clsColors[ch.classification] || clsColors.HUMAN;
      const signalsHtml = (ch.signals || []).map(sig => {{
        const sc = sevColors[sig.severity] || '#6c7086';
        return `
          <div class="chain-signal chain-sev-${{sig.severity}}">
            <div class="sig-header">
              <span class="badge" style="background:${{sc}}22;color:${{sc}}">${{sig.severity}}</span>
              <span class="sig-title">${{sig.title}}</span>
              <span class="sig-meta" style="margin-left:auto">${{sig.source}} · ${{sig.points}}pts</span>
            </div>
            <div class="sig-explanation">${{sig.explanation}}</div>
            <div class="sig-evidence">📊 ${{sig.evidence}}</div>
          </div>`;
      }}).join('');

      const card = document.createElement('div');
      card.className = 'chain-card';
      card.dataset.cls = ch.classification;
      card.dataset.name = ch.actor.toLowerCase();
      card.innerHTML = `
        <div class="chain-card-header" onclick="toggleChain(this)">
          <div class="chain-score-circle" style="background:${{cc.bg}};border-color:${{cc.border}};color:${{cc.color}}">
            ${{ch.score}}
          </div>
          <div style="flex:1">
            <div class="chain-actor-name">${{ch.actor}}</div>
            <div style="display:flex;gap:8px;margin-top:4px">
              <span class="badge" style="background:${{cc.bg}};color:${{cc.color}}">${{ch.classification_es}}</span>
              <span style="font-size:9px;color:var(--subtext)">${{ch.total_signals}} señales forenses</span>
            </div>
            <div class="chain-actor-summary">${{ch.summary}}</div>
          </div>
          <div class="chain-expand-icon">▼</div>
        </div>
        <div class="chain-card-body">
          <div style="color:var(--subtext);font-size:10px;font-weight:bold;letter-spacing:1px;margin-bottom:8px">CADENA DE EVIDENCIA FORENSE:</div>
          <div class="chain-signal-list">${{signalsHtml}}</div>
        </div>`;
      container.appendChild(card);
    }});

    // Search + filter
    const searchEl = document.getElementById('chain-search');
    if (searchEl) {{
      searchEl.addEventListener('input', () => {{
        const q = searchEl.value.toLowerCase();
        document.querySelectorAll('.chain-card').forEach(c => {{
          c.style.display = c.dataset.name.includes(q) ? '' : 'none';
        }});
      }});
    }}
  }})();

  function toggleChain(header) {{
    const card = header.closest('.chain-card');
    card.classList.toggle('open');
  }}

  function filterChains(btn) {{
    document.querySelectorAll('#chain-filter-btns .filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const cls = btn.dataset.cls;
    document.querySelectorAll('.chain-card').forEach(c => {{
      c.style.display = (cls === 'ALL' || c.dataset.cls === cls) ? '' : 'none';
    }});
  }}

  // ── RENDER GLOSSARY ──────────────────────────────────────────────────────────
  (function renderGlossary() {{
    const gl = D.glossary;
    if (!gl) return;

    // Inject glossary section before closing body
    const container = document.querySelector('.container');
    const glossSection = document.createElement('div');
    glossSection.className = 'section';
    glossSection.innerHTML = `
      <div class="section-title">📖 Glosario de Términos y Abreviaturas</div>
      <div style="color:var(--subtext);font-size:11px;margin-bottom:14px;font-style:italic">
        Definiciones para facilitar la comprensión del reporte por parte de fiscales,
        jueces, periodistas y público en general.
      </div>
      <div style="display:flex;gap:12px;align-items:center;margin-bottom:12px;flex-wrap:wrap">
        <input class="glossary-search" type="text" id="glossary-search" placeholder="🔎 Buscar término...">
        <div class="glossary-tabs">
          <button class="glossary-tab active" onclick="switchGlossTab('abbr',this)">ABREVIATURAS</button>
          <button class="glossary-tab" onclick="switchGlossTab('terms',this)">CONCEPTOS</button>
        </div>
      </div>
      <div class="glossary-grid" id="glossary-abbr-grid"></div>
      <div class="glossary-grid" id="glossary-terms-grid" style="display:none"></div>`;
    container.appendChild(glossSection);

    // Populate abbreviations
    const abbrGrid = document.getElementById('glossary-abbr-grid');
    if (abbrGrid && gl.abbreviations) {{
      gl.abbreviations.forEach(e => {{
        abbrGrid.innerHTML += `
          <div class="glossary-entry" data-gl-type="abbr" data-gl-text="${{(e.key+' '+e.def).toLowerCase()}}">
            <div class="glossary-abbr-key">${{e.key}}</div>
            <div class="glossary-def">${{e.def}}</div>
          </div>`;
      }});
    }}

    // Populate terms
    const termsGrid = document.getElementById('glossary-terms-grid');
    if (termsGrid && gl.terms) {{
      gl.terms.forEach(e => {{
        termsGrid.innerHTML += `
          <div class="glossary-entry" data-gl-type="terms" data-gl-text="${{(e.term+' '+e.def).toLowerCase()}}">
            <div class="glossary-key">${{e.term}}</div>
            <div class="glossary-def">${{e.def}}</div>
          </div>`;
      }});
    }}

    // Search
    const gsearch = document.getElementById('glossary-search');
    if (gsearch) {{
      gsearch.addEventListener('input', () => {{
        const q = gsearch.value.toLowerCase();
        document.querySelectorAll('.glossary-entry').forEach(e => {{
          e.classList.toggle('hidden', !e.dataset.glText.includes(q));
        }});
      }});
    }}
  }})();

  function switchGlossTab(type, btn) {{
    document.querySelectorAll('.glossary-tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('glossary-abbr-grid').style.display  = type==='abbr'  ? '' : 'none';
    document.getElementById('glossary-terms-grid').style.display = type==='terms' ? '' : 'none';
  }}

</script>
</body>
</html>"""
