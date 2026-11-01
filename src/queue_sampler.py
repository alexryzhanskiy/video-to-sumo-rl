import os,sys
from pathlib import Path
sys.path.append(os.path.join(os.environ["SUMO_HOME"],"tools"))
import traci
import numpy as np
sys.stdout.reconfigure(encoding="utf-8")

ROOT=Path(__file__).resolve().parents[1]
SUMO=os.path.join(os.environ["SUMO_HOME"],"bin","sumo")
SU=(ROOT/"sumo").as_posix()
LANES=[f"{a}_nC_{i}" for a in ("nN","nE","nS","nW") for i in range(3)]
END=1800; SAMPLE=5

def run(net,rou,seed):
    traci.start([SUMO,"-n",f"{SU}/{net}","-r",f"{SU}/{rou}","--end",str(END),
                 "--seed",str(seed),"--no-step-log","true","--no-warnings","true","--duration-log.disable","true"])
    ts,qs=[],[]
    t=0
    while t<END:
        traci.simulationStep(); t+=1
        if t%SAMPLE==0:
            q=sum(traci.lane.getLastStepHaltingNumber(l) for l in LANES)
            ts.append(t); qs.append(q)
    traci.close()
    return np.array(ts),np.array(qs)

def avg(net,rou,seeds=(1,2,3,4,5)):
    arrs=[]
    for s in seeds:
        _,q=run(net,rou,s); arrs.append(q)
    return np.array(arrs)   # seeds x steps

out={}
for tag,net in [("fixed","intersection.net.xml"),("actuated","intersection_act.net.xml")]:
    A=avg(net,"demand_15.rou.xml")
    out[tag]=A
    print(f"{tag}: steps={A.shape[1]} final={A[:,-1].mean():.0f} max={A.max():.0f} mean={A.mean():.1f}")
np.savez(ROOT/"data"/"queue_fixed_act_x15.npz",
         t=np.arange(SAMPLE,END+1,SAMPLE), fixed=out["fixed"], actuated=out["actuated"])
print("saved npz")
