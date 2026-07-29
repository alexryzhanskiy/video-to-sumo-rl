"""Сборка SUMO-сети перекрёстка Прибузька × Свободи + светофор.

Геометрия: крест из 4 ног. Свободи — ось С-Ю (ноги N,S), Прибузька — В-З (ноги E,W).
Каждый подъезд — 3 полосы: lane0=прямо+направо, lane1=прямо, lane2=ТОЛЬКО налево
(защищённый, под стрелку). Правый — на общий зелёный + на красный (right_on_red = 's').

Светофор: цикл 120с, 8 фаз (снят с countdown-таймеров видео). Левые горят только в свою
фазу-стрелку (после прямой фазы своего направления), правые — 'G' в свою прямую фазу и 's'
во всех остальных, прямые — в свою прямую+жёлтую.

Генерирует sumo/{nodes.nod,edges.edg,conn.con,tls.tll}.xml и компилирует в
sumo/intersection.net.xml через netconvert.

Запуск:
    python src/build_sumo_net.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "sumo"
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SPEED = 13.9        # м/с (~50 км/ч)
LEG = 120.0         # длина ноги, м
NLANES = 3

# узлы: центр (светофор) + 4 конца
NODES = {
    "nC": (0, 0, "traffic_light"),
    "nN": (0, LEG, "priority"),
    "nS": (0, -LEG, "priority"),
    "nE": (LEG, 0, "priority"),
    "nW": (-LEG, 0, "priority"),
}
# Порядок КАК У netconvert (по часовой стрелке от севера) — он индексирует связи так,
# игнорируя явный linkIndex. Светофор строим в этом же порядке, иначе сигналы съедут.
LEGS = ["N", "E", "S", "W"]

# Куда ведёт каждое движение подъезда (нога-цель выезда):
#   подъезд едет противоположно своему направлению; facing -> left/through/right
MOVE_TARGET = {
    "N": {"L": "E", "T": "S", "R": "W"},   # с севера на юг: налево=восток, прямо=юг, направо=запад
    "S": {"L": "W", "T": "N", "R": "E"},
    "E": {"L": "S", "T": "W", "R": "N"},
    "W": {"L": "N", "T": "E", "R": "S"},
}

# netconvert даёт по связи на КАЖДУЮ связь-полосу -> «прямо» = 2 индекса (lane0, lane1).
# Назначаем все 16 индексов явно; светофор строим под них (оба «прямо» — один сигнал).
LEG_LINKS = {}
_c = 0
for leg in LEGS:
    LEG_LINKS[leg] = {}
    LEG_LINKS[leg]["R"] = _c; _c += 1
    LEG_LINKS[leg]["T"] = [_c, _c + 1]; _c += 2
    LEG_LINKS[leg]["L"] = _c; _c += 1
NLINKS = _c  # 16


def edge_in(leg):   return f"n{leg}_nC"
def edge_out(leg):  return f"nC_n{leg}"


def write_nodes():
    lines = ['<nodes>']
    for nid, (x, y, t) in NODES.items():
        lines.append(f'  <node id="{nid}" x="{x}" y="{y}" type="{t}"/>')
    lines.append('</nodes>')
    (OUT / "nodes.nod.xml").write_text("\n".join(lines), encoding="utf-8")


def write_edges():
    lines = ['<edges>']
    for leg in LEGS:
        # въезд: нога -> центр; выезд: центр -> нога
        lines.append(f'  <edge id="{edge_in(leg)}" from="n{leg}" to="nC" '
                     f'numLanes="{NLANES}" speed="{SPEED}" priority="1"/>')
        lines.append(f'  <edge id="{edge_out(leg)}" from="nC" to="n{leg}" '
                     f'numLanes="{NLANES}" speed="{SPEED}" priority="1"/>')
    lines.append('</edges>')
    (OUT / "edges.edg.xml").write_text("\n".join(lines), encoding="utf-8")


def write_connections():
    """lane0=прямо+направо, lane1=прямо, lane2=налево. Явные linkIndex (16 связей)."""
    lines = ['<connections>']
    for leg in LEGS:
        fr = edge_in(leg)
        tgt = MOVE_TARGET[leg]
        lk = LEG_LINKS[leg]
        # направо: lane0 -> правая нога
        lines.append(f'  <connection from="{fr}" to="{edge_out(tgt["R"])}" '
                     f'fromLane="0" toLane="0" tl="nC" linkIndex="{lk["R"]}"/>')
        # прямо: lane0->lane0 (T[0]), lane1->lane1 (T[1])
        lines.append(f'  <connection from="{fr}" to="{edge_out(tgt["T"])}" '
                     f'fromLane="0" toLane="0" tl="nC" linkIndex="{lk["T"][0]}"/>')
        lines.append(f'  <connection from="{fr}" to="{edge_out(tgt["T"])}" '
                     f'fromLane="1" toLane="1" tl="nC" linkIndex="{lk["T"][1]}"/>')
        # налево (защищённый): lane2 -> левая нога
        lines.append(f'  <connection from="{fr}" to="{edge_out(tgt["L"])}" '
                     f'fromLane="2" toLane="2" tl="nC" linkIndex="{lk["L"]}"/>')
    lines.append('</connections>')
    (OUT / "conn.con.xml").write_text("\n".join(lines), encoding="utf-8")


def state(spec):
    """spec: dict (leg,move)->символ; недостающие = 'r'. -> строка длины NLINKS (16).
    move 'T' заполняет оба индекса полос «прямо»."""
    s = ["r"] * NLINKS
    for (leg, m), ch in spec.items():
        idx = LEG_LINKS[leg][m]
        for i in (idx if isinstance(idx, list) else [idx]):
            s[i] = ch
    return "".join(s)


def write_tls():
    # правые: 'G' в свою прямую фазу (+жёлтую), 's' во всех остальных (right_on_red)
    def rights(active_legs, ch="G"):
        d = {}
        for leg in LEGS:
            d[(leg, "R")] = ch if leg in active_legs else "s"
        return d

    SVB, PRB = ["N", "S"], ["E", "W"]
    phases = []
    # 1) Свободи прямо (46): N,S прямо G; их правые G; левые r; Прибузька прямо r, правые s
    sp = {(l, "T"): "G" for l in SVB}; sp.update(rights(SVB))
    phases.append((46, state(sp)))
    # 2) Свободи жёлтый (3)
    sp = {(l, "T"): "y" for l in SVB}; sp.update(rights(SVB))
    phases.append((3, state(sp)))
    # 3) Свободи стрелка налево (12 зелёная + 3 жёлтая = 15): N,S левые; правые s
    phases.append((12, state({**{(l, "L"): "G" for l in SVB}, **rights([])})))
    phases.append((3,  state({**{(l, "L"): "y" for l in SVB}, **rights([])})))
    # 4) all-red (4): только правые s
    phases.append((4, state(rights([]))))
    # 5) Прибузька прямо (30)
    sp = {(l, "T"): "G" for l in PRB}; sp.update(rights(PRB))
    phases.append((30, state(sp)))
    # 6) Прибузька жёлтый (3)
    sp = {(l, "T"): "y" for l in PRB}; sp.update(rights(PRB))
    phases.append((3, state(sp)))
    # 7) Прибузька стрелка налево (12 зелёная + 3 жёлтая = 15)
    phases.append((12, state({**{(l, "L"): "G" for l in PRB}, **rights([])})))
    phases.append((3,  state({**{(l, "L"): "y" for l in PRB}, **rights([])})))
    # 8) all-red (4)
    phases.append((4, state(rights([]))))

    assert sum(d for d, _ in phases) == 120, "цикл не 120с"
    lines = ['<additional>',
             '  <tlLogic id="nC" type="static" programID="real" offset="0">']
    for dur, st in phases:
        lines.append(f'    <phase duration="{dur}" state="{st}"/>')
    lines.append('  </tlLogic>')
    lines.append('</additional>')
    (OUT / "tls.tll.xml").write_text("\n".join(lines), encoding="utf-8")
    return phases


def main():
    OUT.mkdir(exist_ok=True)
    write_nodes(); write_edges(); write_connections(); phases = write_tls()
    print(f"[net] фазы (dur, state по {NLINKS} связям: на ногу R,T,T,L; порядок ног {','.join(LEGS)}):")
    for dur, st in phases:
        print(f"   {dur:>3}с  {st}")

    net = OUT / "intersection.net.xml"
    cmd = ["netconvert",
           "--node-files", str(OUT / "nodes.nod.xml"),
           "--edge-files", str(OUT / "edges.edg.xml"),
           "--connection-files", str(OUT / "conn.con.xml"),
           "--tllogic-files", str(OUT / "tls.tll.xml"),
           "--output-file", str(net),
           "--no-turnarounds", "true"]
    print("\n[net] netconvert ...")
    p = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(p.stdout)
    sys.stderr.write(p.stderr)
    if p.returncode == 0:
        print(f"\n[net] OK -> {net}")
    else:
        print(f"\n[net] netconvert упал (код {p.returncode})")


if __name__ == "__main__":
    main()
