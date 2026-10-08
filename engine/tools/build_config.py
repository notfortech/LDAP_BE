"""Emits the v1.0.0 engine configuration.

Config is generated from this single source so the twelve construct
blocks stay structurally identical and cannot drift by hand-editing.
Framework mappings are transcribed from docs/SKILLS_TAXONOMY.md in the
LDAP_ProjUI repository; mapping_strength records that document's own
honest note that some cells are weaker than others.
"""
import json, pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "config" / "v1.0.0"

# (id, display, definition, indicators, aqf, acara, csfw, asc, strength, limits)
C = [
 ("SK_COMMUNICATION","Communication & Expression",
  "Conveys information clearly and adjusts detail and tone to the audience.",
  ["States the essential point before the detail","Adjusts register for the listener","Checks understanding rather than assuming it"],
  "Communicates knowledge and ideas to a range of audiences","Literacy","Communicate for work",
  "Speaking / Active Listening / Writing","strong",
  ["Written expression is not directly observed; items infer it from choice behaviour"]),
 ("SK_CRITICAL_THINKING","Critical Thinking & Problem-Solving",
  "Questions assumptions and analyses a situation before acting.",
  ["Seeks disconfirming information","Separates symptom from cause","Evaluates more than one option"],
  "Analyses, synthesises and evaluates information","Critical & Creative Thinking","Identify and solve problems",
  "Critical Thinking / Complex Problem Solving","strong",
  ["Situational items constrain the option set, so option generation is not observed"]),
 ("SK_DECISION_MAKING","Decision-Making & Judgement",
  "Weighs trade-offs and decides under incomplete information or time pressure.",
  ["Acts without complete information when acting is warranted","Names the trade-off accepted","Escalates when the decision is not theirs"],
  "Exercises judgement across a range of contexts","Critical & Creative Thinking","Make decisions",
  "Judgment and Decision Making","strong",
  ["Real decisions carry consequence; a scenario does not, which weakens behavioural fidelity"]),
 ("SK_COLLABORATION","Collaboration & Teamwork",
  "Contributes reliably in a group and handles disagreement constructively.",
  ["Raises a concern directly rather than around the person","Accepts a group decision it argued against","Shares credit and information"],
  "Works autonomously and collaboratively","Personal & Social Capability","Connect and work with others",
  "Coordination / Social Perceptiveness","strong",
  ["Self-report of group behaviour is subject to social desirability bias"]),
 ("SK_ACCOUNTABILITY","Accountability & Reliability",
  "Owns outcomes, follows through, and is honest about mistakes.",
  ["Reports a problem it caused before being asked","Follows through when inconvenient","Does not distribute blame"],
  "Takes responsibility within defined parameters","Personal & Social Capability","Work with roles, rights and protocols",
  "Monitoring","strong",
  ["Strongly susceptible to social desirability; the correct answer is often obvious"]),
 ("SK_ADAPTABILITY","Adaptability & Resilience",
  "Responds to change, setback or ambiguity without disengaging.",
  ["Re-plans rather than stalls","Treats a setback as information","Tolerates unresolved ambiguity"],
  "Adapts knowledge and skills to new or changing contexts","Personal & Social Capability",
  "Navigate the world of work","Active Learning","moderate",
  ["Resilience over time cannot be observed in a single sitting"]),
 ("SK_DIGITAL","Digital & Technology Capability",
  "Uses digital tools appropriately and safely for the task at hand.",
  ["Chooses a proportionate tool","Recognises a data-handling risk","Seeks help before improvising with unfamiliar systems"],
  "Applies technical and digital skills appropriate to level","Digital Literacy","Work in a digital world",
  "Technology Design","moderate",
  ["Measures judgement about tools, not operational skill with any tool"]),
 ("SK_PLANNING","Planning & Organisation",
  "Sequences work, manages time and resources, and meets deadlines.",
  ["Orders work by dependency, not arrival","Protects time for committed work","Renegotiates a deadline early"],
  "Plans and executes tasks to a required standard","(no clean mapping)","Plan and organise",
  "Time Management","moderate",
  ["No Australian Curriculum general capability maps cleanly; the curriculum column is weak here"]),
 ("SK_INITIATIVE","Initiative & Creativity",
  "Self-directs, proposes improvements, and generates options beyond the obvious.",
  ["Acts within mandate without being prompted","Proposes an improvement with a reason","Offers an option not presented"],
  "Generates novel or improved approaches","Critical & Creative Thinking","Create and innovate",
  "Active Learning / Learning Strategies","moderate",
  ["Fixed-option items structurally limit observation of generative behaviour"]),
 ("SK_ETHICS","Ethical & Professional Practice",
  "Understands workplace rights and protocols and acts with integrity.",
  ["Applies a rule it finds inconvenient","Raises a concern through the right channel","Declines an improper request"],
  "Acts within ethical and professional expectations","Ethical Understanding","Work with roles, rights and protocols",
  "Service Orientation","moderate",
  ["The defensible answer is usually identifiable, which compresses the score range upward"]),
 ("SK_NUMERACY","Numeracy & Data Literacy",
  "Interprets numbers and data correctly enough to act on them.",
  ["Notices an implausible figure","Distinguishes proportion from count","Acts on what the number supports, not more"],
  "Applies quantitative reasoning to real problems","Numeracy","Get the work done",
  "Operations Analysis","moderate",
  ["Situational items test interpretation, not computation; this is narrower than numeracy"]),
 ("SK_CAREER","Career Self-Management & Navigation",
  "Understands own goals and pathways and how to seek help and opportunity.",
  ["Can name a concrete next step","Seeks help from an appropriate source","Relates current activity to a pathway"],
  "Understands own standing relative to a qualification pathway","(no clean mapping)","Manage career and work life",
  "(no clean mapping)","weak",
  ["Neither the Australian Curriculum nor the core-competency layer maps cleanly",
   "The weakest-grounded construct of the twelve; carried because it is what institutions ask for"]),
]

SIG = {
 "SK_COMMUNICATION":"SIG_COMMUNICATION_TRANSPARENCY","SK_CRITICAL_THINKING":"SIG_CRITICAL_VERIFICATION",
 "SK_DECISION_MAKING":"SIG_DECISION_TRIAGE","SK_COLLABORATION":"SIG_COLLABORATION_DIRECTNESS",
 "SK_ACCOUNTABILITY":"SIG_ACCOUNTABILITY_OWNERSHIP","SK_ADAPTABILITY":"SIG_ADAPTABILITY_RESPONSE",
 "SK_DIGITAL":"SIG_DIGITAL_TOOL_JUDGEMENT","SK_PLANNING":"SIG_PLANNING_PRIORITISATION",
 "SK_INITIATIVE":"SIG_INITIATIVE_PROACTIVITY","SK_ETHICS":"SIG_ETHICS_INTEGRITY",
 "SK_NUMERACY":"SIG_NUMERACY_INTERPRETATION","SK_CAREER":"SIG_CAREER_DIRECTION",
}

constructs = []
for cid, name, defn, ind, aqf, acara, csfw, asc, strength, limits in C:
    constructs.append({
        "construct_id": cid, "display_name": name, "definition": defn,
        "observable_indicators": ind,
        "derived_from": [{"signal_id": SIG[cid], "weight": 1.0}],
        "evidence": {
            "framework_basis": {"aqf_theme": aqf, "acara_general_capability": acara,
                                "csfw_area": csfw, "asc_core_competency": asc},
            "mapping_strength": strength,
            "item_support": 2,
            "validation_status": "framework-aligned",
            "empirical_validation": "none",
            "confidence": "medium" if strength == "strong" else "low-medium",
            "known_limitations": limits,
        }})

(OUT/"constructs.json").write_text(json.dumps({"constructs": constructs}, indent=2)+"\n")
(OUT/"scale.json").write_text(json.dumps({
  "scale_id":"four_point_sj","options":{"A":1.0,"B":0.75,"C":0.5,"D":0.25},
  "rationale":"Four ordered options force a directional choice and remove a neutral midpoint. "
              "Equal 0.25 spacing asserts ordinal rank only; it does not claim equal psychological intervals."
}, indent=2)+"\n")
(OUT/"bands.json").write_text(json.dumps({
  "band_set_id":"four_band_quartile",
  "bands":[{"label":"Emerging","min":0.0,"max":0.25},{"label":"Developing","min":0.25,"max":0.5},
           {"label":"Proficient","min":0.5,"max":0.75},{"label":"Strong","min":0.75,"max":1.0}],
  "boundary_rule":"lower_inclusive_upper_exclusive_except_top",
  "rationale":"Quartile cut-points on the normalised score. These are reporting conventions chosen for "
              "interpretability, not empirically derived cut-scores, and no external criterion validates them."
}, indent=2)+"\n")
print("wrote constructs, scale, bands")
