"""Этап 3a — интерактивная разметка гейтов на ВЫПРЯМЛЕННОМ кадре.

Два типа гейтов (каждый — отрезок из 2 кликов):
  * stop  — стоп-линия подъезда: точка счёта (когда ТС покидает подъезд) и опознание
            въезда. Рисуй по одной на каждый подъезд, что видит ЭТА камера крупно.
  * exit  — выездной гейт по ноге перекрёстка: куда ТС ушло. По одному на каждую ногу.

Движение трека потом = (какую stop пересёк на въезде) -> (какой exit пересёк на выезде),
маппится в прямо/налево/направо. Размечай на выпрямленном кадре (calib/<cam>_undistorted_ref.jpg),
т.к. координаты треков спрямляются в ту же систему.

Управление:
    s        — режим stop-линии (красный)
    e        — режим exit-гейта (голубой)
    ЛКМ      — точка; 2 точки = гейт (авто-имя stop0/exit0/…)
    u        — отменить последний гейт (или незавершённую точку)
    w        — сохранить в calib/gates_<camera>.json
    q / Esc  — выход

Запуск:
    python src/zones_pick.py --camera center
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROLE_COLOR = {"stop": (0, 0, 255), "exit": (255, 200, 0)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Разметка гейтов (стоп-линии и выезды)")
    ap.add_argument("--camera", required=True)
    ap.add_argument("--display-width", type=int, default=1500)
    args = ap.parse_args()

    bg_path = ROOT / "calib" / f"{args.camera}_undistorted_ref.jpg"
    if not bg_path.exists():
        raise SystemExit(f"Нет выпрямленного кадра {bg_path}. Сначала Этап 2 (calib_fisheye).")
    frame = cv2.imread(str(bg_path))
    H, W = frame.shape[:2]
    scale = args.display_width / W
    disp = (args.display_width, int(H * scale))

    out_path = ROOT / "calib" / f"gates_{args.camera}.json"
    gates: list[dict] = []
    if out_path.exists():
        gates = json.load(open(out_path, encoding="utf-8")).get("gates", [])
        print(f"[zones] подгрузил {len(gates)} гейтов из {out_path.name}")

    state = {"role": "stop", "pending": None}

    def next_id(role):
        n = sum(1 for g in gates if g["role"] == role)
        return f"{role}{n}"

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            pt = [x / scale, y / scale]
            if state["pending"] is None:
                state["pending"] = pt
            else:
                gates.append({"id": next_id(state["role"]), "role": state["role"],
                              "points": [state["pending"], pt]})
                print(f"[zones] + {gates[-1]['id']}")
                state["pending"] = None

    win = f"zones: {args.camera}  (s=stop e=exit u=undo w=save q=quit)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, *disp)
    cv2.setMouseCallback(win, on_mouse)
    print("[zones] s=стоп-линия, e=выезд; 2 клика = гейт; w=сохранить")

    while True:
        vis = cv2.resize(frame, disp)
        for g in gates:
            (x1, y1), (x2, y2) = g["points"]
            p1 = (int(x1 * scale), int(y1 * scale))
            p2 = (int(x2 * scale), int(y2 * scale))
            col = ROLE_COLOR[g["role"]]
            cv2.line(vis, p1, p2, col, 3)
            mid = ((p1[0] + p2[0]) // 2, (p1[1] + p2[1]) // 2)
            cv2.putText(vis, g["id"], (mid[0] + 5, mid[1] - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
        if state["pending"] is not None:
            pp = (int(state["pending"][0] * scale), int(state["pending"][1] * scale))
            cv2.circle(vis, pp, 5, ROLE_COLOR[state["role"]], -1)
        cv2.putText(vis, f"mode={state['role']}  stops={sum(1 for g in gates if g['role']=='stop')}"
                    f"  exits={sum(1 for g in gates if g['role']=='exit')}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        cv2.imshow(win, vis)
        k = cv2.waitKey(20) & 0xFF
        if k in (ord('q'), 27):
            break
        elif k == ord('s'):
            state["role"] = "stop"; state["pending"] = None
        elif k == ord('e'):
            state["role"] = "exit"; state["pending"] = None
        elif k == ord('u'):
            if state["pending"] is not None:
                state["pending"] = None
            elif gates:
                removed = gates.pop()
                print(f"[zones] - {removed['id']}")
        elif k == ord('w'):
            json.dump({"camera": args.camera, "image_size": [W, H], "gates": gates},
                      open(out_path, "w", encoding="utf-8"), indent=2)
            print(f"[zones] сохранено {len(gates)} гейтов -> {out_path}")

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
