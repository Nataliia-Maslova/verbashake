"""
engine/curriculum_order.py — where Grammar lessons added later sit in the
curriculum's own order (2026-10-04).

Everything that walks the Grammar curriculum in order — My Path's frontier
(recommender._grammar_frontier_unit), "Easier/Harder", the lesson picker,
sidebar position, "Next lesson" — used to sort by raw lesson_id. That is
fine for the original lessons 1-182, but a lesson appended later gets a
higher id than everything else, so a student would reach, say, the A2
Past Continuous lesson only after the C1 Third conditional. PLACE_AFTER
puts such a lesson right after the lesson it belongs next to; any lesson
not listed keeps its numeric place. Lessons 174-182 (added 2026-08-21) were
placed too, at Наталья's request, 2026-10-04 — this moves the path for
students who were past them, which she accepted.
"""
from __future__ import annotations

# new_lesson_id: place directly after this lesson_id (chains allowed —
# 186 after 185 after 165 keeps them in this order).
PLACE_AFTER: dict[int, int] = {
    # Present / future basics
    183: 83,    # be going to — after the will-future block (78-83)
    # After the Past Simple block (114-138)
    184: 138,   # Past Continuous
    178: 184,   # Used to / would (past habits)
    175: 178,   # Relative clauses — examples use the past ("the keys that I lost yesterday")
    180: 175,   # Phrasal verbs — examples use the past ("gave up smoking last year")
    # Passive / verb patterns
    181: 159,   # Causative have/get done — after the passive block (144-147, 156-159)
    182: 170,   # It + be + adjective + to-infinitive — after verb + infinitive/gerund (167-170)
    # After the Present Perfect block (160-165): perfect and continuous forms, then what needs them
    185: 165,   # Present Perfect Continuous
    186: 185,   # Past Perfect
    176: 186,   # Third conditional — "If I had known..." needs the Past Perfect
    179: 176,   # Wishes — "I wish I had..."
    187: 179,   # Past Perfect Continuous
    174: 187,   # Reported speech — backshift to had eaten / was working
    177: 174,   # Modals of deduction — must/might/can't have done
    188: 177,   # Future Continuous
    189: 188,   # Future Perfect
    190: 189,   # Future Perfect Continuous
}


# Language-path lessons (engine/target_grammar_paths.py, ids 1000+), each
# placed next to the base lesson it grammatically belongs with (2026-10-04,
# Наталья: "расставь мовні шляхи отдельно для каждого языка"). Ids are
# unique per language, so one map serves all; lessons of one language that
# share a neighbour are chained to each other to keep their own order.
LANGUAGE_PATH_PLACE_AFTER: dict[int, int] = {
    # Ukrainian
    1000: 1, 1001: 46, 1002: 184, 1135: 1002, 1003: 1135, 1136: 1003, 1137: 1136,
    1005: 1137, 1004: 1005, 1006: 143,
    # Russian
    1007: 1, 1008: 46, 1009: 184, 1132: 1009, 1010: 1132, 1133: 1010, 1134: 1133,
    1011: 1134, 1012: 1011, 1013: 143,
    # Polish
    1014: 1, 1015: 46, 1016: 184, 1138: 1016, 1017: 1138, 1139: 1017, 1140: 1139,
    1018: 30, 1019: 143,
    # Czech
    1087: 1, 1088: 46, 1089: 184, 1141: 1089, 1090: 1141, 1142: 1090, 1143: 1142,
    1091: 112, 1092: 139,
    # Bulgarian
    1081: 19, 1082: 89, 1083: 184, 1144: 1083, 1084: 1144, 1145: 1084, 1146: 1145,
    1085: 112, 1086: 174,
    # Spanish
    1021: 1, 1020: 20, 1023: 46, 1022: 101, 1025: 95, 1105: 138, 1106: 1105, 1107: 1106,
    1024: 184, 1026: 139,
    # Portuguese
    1036: 20, 1038: 95, 1040: 105, 1117: 138, 1118: 1117, 1119: 1118, 1037: 184, 1039: 182,
    # French
    1027: 1, 1029: 33, 1030: 46, 1031: 95, 1108: 138, 1109: 1108, 1110: 1109, 1028: 184,
    # Italian
    1032: 1, 1034: 41, 1035: 95, 1114: 138, 1115: 1114, 1116: 1115, 1033: 184,
    # Catalan
    1041: 1, 1042: 41, 1043: 95, 1120: 138, 1121: 1120, 1122: 1121,
    # German
    1044: 1, 1045: 46, 1046: 1045, 1048: 64, 1047: 65, 1049: 103, 1050: 112,
    1111: 138, 1112: 1111, 1113: 1112,
    # Dutch
    1051: 1, 1053: 65, 1054: 89, 1052: 103, 1055: 112, 1123: 138, 1124: 1123, 1125: 1124,
    # Swedish
    1099: 1, 1100: 19, 1101: 1100, 1102: 1101, 1104: 64, 1103: 103,
    1126: 138, 1127: 1126, 1128: 1127,
    # Romanian
    1075: 19, 1076: 24, 1078: 46, 1080: 64, 1077: 89, 1079: 112,
    1129: 138, 1130: 1129, 1131: 1130,
    # Turkish
    1093: 1, 1096: 4, 1095: 21, 1094: 46, 1098: 89, 1147: 138, 1097: 184,
    # Japanese
    1056: 8, 1061: 31, 1057: 45, 1058: 48, 1059: 50, 1148: 65, 1060: 1148, 1149: 1060,
    1150: 1149, 1062: 98,
    # Korean
    1063: 8, 1065: 31, 1064: 45, 1066: 59, 1067: 98, 1068: 103,
    1151: 138, 1152: 1151, 1153: 1152,
    # Chinese
    1069: 31, 1074: 89, 1072: 106, 1070: 184, 1071: 1070, 1073: 1071,
}
PLACE_AFTER.update(LANGUAGE_PATH_PLACE_AFTER)


def order_key(lesson_id: int) -> tuple[int, ...]:
    """
    Sort key for Grammar lesson ids in curriculum order: a base lesson is
    (id,); a placed lesson is its neighbour's key + (id,), so it sorts
    right after the neighbour (and the neighbour's other placed lessons),
    before the next base lesson. Among lessons placed after the same
    neighbour, base lessons come before language-path ones (lower ids).
    """
    chain = [lesson_id]
    while chain[-1] in PLACE_AFTER and len(chain) < 50:
        chain.append(PLACE_AFTER[chain[-1]])
    return tuple(reversed(chain))


def sort_lessons(lesson_ids) -> list[int]:
    return sorted(lesson_ids, key=order_key)
