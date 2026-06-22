#!/usr/bin/env python3
"""Regenerate dashboard_data.json and inject it into dashboard.html."""

import sqlite3, math, json, re, sys, os
from collections import defaultdict
from espn_schedule import get_week_date_range

LOWER_IS_BETTER = {'era', 'whip'}
CATEGORIES = ['r', 'hr', 'rbi', 'sb', 'avg', 'ops', 'k', 'qs', 'sv', 'hd', 'era', 'whip']
BAT_CATS = ['r','hr','rbi','sb','avg','ops']
PIT_CATS = ['k','qs','sv','hd','era','whip']

def norm_cdf(z):
    return 0.5*(1.0+math.erf(z/math.sqrt(2.0)))

def parse_ip(ip_val):
    if ip_val is None: return 0.0
    whole=int(ip_val); return whole+round(ip_val-whole,1)*10/3

def get_weekly_stats(conn, week):
    start, end = get_week_date_range(week)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.team_name, t.r, t.hr, t.rbi, t.sb, t.avg, t.ops,
               t.k, t.qs, t.sv, t.hd, t.era, t.whip
        FROM team_day_snapshots t
        INNER JOIN (SELECT team_name, MAX(snapshot_date) as max_date
            FROM team_day_snapshots WHERE snapshot_date BETWEEN ? AND ?
            GROUP BY team_name) latest
        ON t.team_name=latest.team_name AND t.snapshot_date=latest.max_date
        WHERE t.snapshot_date BETWEEN ? AND ?
    """, (start, end, start, end))
    return {row[0]: dict(zip(CATEGORIES, row[1:])) for row in cursor.fetchall()}

def week_stds(ts):
    res = {}
    for cat in CATEGORIES:
        vals=[ts[t].get(cat) or 0 for t in ts]; mean=sum(vals)/len(vals)
        std=math.sqrt(sum((v-mean)**2 for v in vals)/len(vals))
        res[cat]=(mean, std)
    return res

def cwp(va, vb, std, cat):
    if std==0: return 0.5
    diff=(va-vb)/std
    if cat in LOWER_IS_BETTER: diff=-diff
    return norm_cdf(diff)

def pbin(probs):
    dp=[0.0]*(len(probs)+1); dp[0]=1.0
    for p in probs:
        ndp=[0.0]*(len(probs)+1)
        for j in range(len(probs)+1):
            if not dp[j]: continue
            if j+1<=len(probs): ndp[j+1]+=dp[j]*p
            ndp[j]+=dp[j]*(1-p)
        dp=ndp
    return sum(dp[7:])+0.5*dp[6]

def zscore_players(players, cats, lower_better=set(), min_key=None, min_val=0, ip_weight=None):
    """ip_weight: key of the IP (decimal) field. When set, ERA/WHIP z-scores are
    computed as IP-weighted contributions so a 12-IP 9.00 ERA barely hurts."""
    pool=[p for p in players if not min_key or p[min_key]>=min_val]
    if not pool: return pool
    # Precompute IP-weighted pool averages for lower_better cats
    ip_avgs={}
    if ip_weight:
        total_ip=sum(p.get(ip_weight,0) or 0 for p in pool)
        if total_ip>0:
            for cat in lower_better:
                ip_avgs[cat]=sum((p.get(cat) or 0)*(p.get(ip_weight) or 0) for p in pool)/total_ip
    for cat in cats:
        if ip_weight and cat in ip_avgs:
            # contribution = (avg - val) * ip  =>  positive means better than avg
            vals=[(ip_avgs[cat]-(p.get(cat) or 0))*(p.get(ip_weight) or 0) for p in pool]
            mean=sum(vals)/len(vals)
            std=math.sqrt(sum((v-mean)**2 for v in vals)/len(vals))
            for p,v in zip(pool,vals):
                p[f'z_{cat}']=(v-mean)/std if std>0 else 0
        else:
            vals=[p[cat] for p in pool]; mean=sum(vals)/len(vals)
            std=math.sqrt(sum((v-mean)**2 for v in vals)/len(vals))
            for p in pool:
                z=(p[cat]-mean)/std if std>0 else 0
                if cat in lower_better: z=-z
                p[f'z_{cat}']=z
    for p in pool: p['z_total']=sum(p[f'z_{cat}'] for cat in cats)
    return sorted(pool, key=lambda p: p["z_total"], reverse=True)

def find_best_trade(team_a, weak_cat, team_avg_z, all_players, team_players, exclude_used):
    FAIR_WINDOW=2.0
    candidates=[p for p in all_players if p['team']!=team_a and p['name'] not in exclude_used
                and f'z_{weak_cat}' in p and p[f'z_{weak_cat}']>0.5]
    candidates.sort(key=lambda p: p[f'z_{weak_cat}'], reverse=True)
    for inc in candidates[:8]:
        partner=inc['team']
        partner_z=team_avg_z.get(partner,{})
        partner_need_cats=[c for c,z in sorted(partner_z.items(),key=lambda x:x[1])[:4] if z<0.5]
        a_offers=[p for p in team_players[team_a] if p['name'] not in exclude_used
                  and abs(p['z_total']-inc['z_total'])<=FAIR_WINDOW]
        best_out=None; best_fit=-99
        for offer in a_offers:
            fit=sum(offer.get(f'z_{c}',0) for c in partner_need_cats)
            if fit>best_fit: best_fit=fit; best_out=offer
        if best_out:
            gain=inc[f'z_{weak_cat}']-best_out.get(f'z_{weak_cat}',0)
            return inc,[best_out],partner,gain
        a_team=sorted(team_players[team_a],key=lambda p:p['z_total'],reverse=True)
        for i,p1 in enumerate(a_team[:6]):
            if p1['name'] in exclude_used: continue
            for p2 in a_team[i+1:7]:
                if p2['name'] in exclude_used: continue
                if abs(p1['z_total']+p2['z_total']-inc['z_total'])<=FAIR_WINDOW:
                    fit=sum(p1.get(f'z_{c}',0)+p2.get(f'z_{c}',0) for c in partner_need_cats)
                    if fit>0:
                        gain=inc[f'z_{weak_cat}']-max(p1.get(f'z_{weak_cat}',0),p2.get(f'z_{weak_cat}',0))
                        return inc,[p1,p2],partner,gain
    return None

# ── Find DB ───────────────────────────────────────────────────────────────────
script_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.dirname(script_dir) if os.path.basename(script_dir) == "code" else script_dir
db_path = os.path.join(script_dir, 'fantasy_baseball.db')
html_template = os.path.join(repo_root, "index.html")
if not os.path.exists(html_template):
    html_template = os.path.join(script_dir, "dashboard.html")

if not os.path.exists(db_path):
    print(f"ERROR: database not found at {db_path}"); sys.exit(1)
if not os.path.exists(html_template):
    print(f"ERROR: dashboard.html not found at {html_template}"); sys.exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# ── Standings ─────────────────────────────────────────────────────────────────
cursor.execute("""
    SELECT TRIM(team_name), owner, wins, losses, ties, pct, games_back,
           r, hr, rbi, sb, avg, ops, k, qs, sv, hd, era, whip
    FROM standings_snapshots
    WHERE snapshot_date=(SELECT MAX(snapshot_date) FROM standings_snapshots)
    ORDER BY pct DESC
""")
actual={}
for row in cursor.fetchall():
    actual[row[0]]={'owner':row[1],'w':row[2],'l':row[3],'t':row[4],'pct':row[5],'gb':row[6],
        'r':row[7],'hr':row[8],'rbi':row[9],'sb':row[10],'avg':row[11],'ops':row[12],
        'k':row[13],'qs':row[14],'sv':row[15],'hd':row[16],'era':row[17],'whip':row[18]}

# ── Expected record + weekly progression ─────────────────────────────────────
team_zscores=defaultdict(lambda:defaultdict(list))
exp_wins=defaultdict(float); exp_losses=defaultdict(float)
weekly_exp={t:[] for t in actual}
cum_w=defaultdict(float); cum_l=defaultdict(float)

for week in range(2,13):
    stats=get_weekly_stats(conn,week)
    if len(stats)<10: continue
    cs=week_stds(stats); teams=list(stats.keys())
    for i,ta in enumerate(teams):
        for tb in teams[i+1:]:
            probs=[cwp(stats[ta].get(c) or 0,stats[tb].get(c) or 0,cs[c][1],c) for c in CATEGORIES]
            p=pbin(probs)
            exp_wins[ta]+=p; exp_losses[ta]+=1-p
            exp_wins[tb]+=1-p; exp_losses[tb]+=p
            cum_w[ta]+=p; cum_l[ta]+=1-p
            cum_w[tb]+=1-p; cum_l[tb]+=p
    for cat in CATEGORIES:
        vals=[(t,stats[t].get(cat) or 0) for t in stats]
        values=[v for _,v in vals]; mean=sum(values)/len(values)
        std=math.sqrt(sum((v-mean)**2 for v in values)/len(values))
        if std==0: continue
        for team,val in vals:
            z=(val-mean)/std
            if cat in LOWER_IS_BETTER: z=-z
            team_zscores[team][cat].append(z)
    for t in actual:
        cw=cum_w[t]; cl=cum_l[t]
        weekly_exp[t].append({'week':week,'cum_w':round(cw,1),'cum_l':round(cl,1)})

team_avg_z={t:{c:sum(zs)/len(zs) if zs else 0 for c,zs in team_zscores[t].items()} for t in team_zscores}

# Actual by week
cursor.execute("SELECT DISTINCT snapshot_date FROM standings_snapshots ORDER BY snapshot_date")
snap_dates=[r[0] for r in cursor.fetchall()]
actual_by_week={}
from datetime import datetime
for sd in snap_dates:
    d=datetime.strptime(sd,'%Y-%m-%d')
    for w in range(1,20):
        s,e=get_week_date_range(w)
        ds=datetime.strptime(str(s),'%Y-%m-%d'); de=datetime.strptime(str(e),'%Y-%m-%d')
        if ds<=d<=de:
            cursor.execute("SELECT TRIM(team_name),wins,losses,ties,pct FROM standings_snapshots WHERE snapshot_date=?",(sd,))
            actual_by_week[w]={r[0]:{'w':r[1],'l':r[2],'t':r[3],'pct':round(r[4],3)} for r in cursor.fetchall()}
            break

exp_order=sorted(actual.keys(),key=lambda t:-exp_wins[t])

# ── Weekly top players (most recently completed week) ────────────────────────
_latest_week=max((w for w in range(2,20) if len(get_weekly_stats(conn,w))>=10),default=None)
weekly_top_batters=[]; weekly_top_pitchers=[]
if _latest_week:
    _ws,_we=get_week_date_range(_latest_week)
    cursor.execute("""
        SELECT p.player_name,
            (SELECT team_name FROM player_snapshots p2 WHERE p2.player_name=p.player_name AND p2.player_type='batter'
             AND p2.week=? ORDER BY snapshot_date DESC LIMIT 1),
            SUM(CASE WHEN h_ab LIKE '%/%' AND h_ab!='--/--' THEN CAST(SUBSTR(h_ab,1,INSTR(h_ab,'/')-1) AS REAL) ELSE 0 END),
            SUM(CASE WHEN h_ab LIKE '%/%' AND h_ab!='--/--' THEN CAST(SUBSTR(h_ab,INSTR(h_ab,'/')+1) AS REAL) ELSE 0 END),
            SUM(COALESCE(r,0)),SUM(COALESCE(hr,0)),SUM(COALESCE(rbi,0)),SUM(COALESCE(bb,0)),SUM(COALESCE(sb,0)),
            AVG(CASE WHEN avg IS NOT NULL THEN avg ELSE NULL END),
            AVG(CASE WHEN ops IS NOT NULL THEN ops ELSE NULL END)
        FROM player_snapshots p WHERE player_type='batter' AND week=?
          AND snapshot_date=(SELECT MAX(snapshot_date) FROM player_snapshots p3
            WHERE p3.player_name=p.player_name AND p3.week=?)
          AND player_name NOT IN ('Empty','__Empty__')
        GROUP BY player_name
        HAVING SUM(CASE WHEN h_ab LIKE '%/%' AND h_ab!='--/--' THEN CAST(SUBSTR(h_ab,INSTR(h_ab,'/')+1) AS REAL) ELSE 0 END)>=3
    """, (_latest_week, _latest_week, _latest_week))
    _wb=[]
    for row in cursor.fetchall():
        nm,tm,h,ab,r,hr,rbi,bb,sb,avg,ops=row
        if not tm: continue
        _wb.append({'name':nm,'team':tm,'ab':int(ab or 0),'r':round(r,1),'hr':round(hr,1),
                    'rbi':round(rbi,1),'sb':round(sb,1),'avg':round(avg or 0,3),'ops':round(ops or 0,3),'ptype':'bat'})
    weekly_top_batters=zscore_players(_wb,BAT_CATS,min_key='ab',min_val=3)[:10]
    for i,b in enumerate(weekly_top_batters): b['rank']=i+1; b['score']=round(b['z_total'],2); b['week']=_latest_week

    cursor.execute("""
        SELECT p.player_name,
            (SELECT team_name FROM player_snapshots p2 WHERE p2.player_name=p.player_name AND p2.player_type='pitcher'
             AND p2.week=? ORDER BY snapshot_date DESC LIMIT 1),
            SUM(ip),SUM(COALESCE(h,0)),SUM(COALESCE(er,0)),SUM(COALESCE(bb,0)),
            SUM(COALESCE(k,0)),SUM(COALESCE(qs,0)),SUM(COALESCE(sv,0)),SUM(COALESCE(hd,0))
        FROM player_snapshots p WHERE player_type='pitcher' AND week=? AND ip IS NOT NULL AND ip>0
          AND snapshot_date=(SELECT MAX(snapshot_date) FROM player_snapshots p3
            WHERE p3.player_name=p.player_name AND p3.week=?)
          AND player_name NOT IN ('Empty','__Empty__')
        GROUP BY player_name HAVING SUM(ip)>=1
    """, (_latest_week, _latest_week, _latest_week))
    _wp=[]
    for row in cursor.fetchall():
        nm,tm,ip,h,er,bb,k,qs,sv,hd=row
        if not tm: continue
        ip_dec=parse_ip(ip)
        ip_disp=f"{int(ip_dec)}.{round((ip_dec-int(ip_dec))*3)}"
        era=round((er/ip_dec)*9,2) if ip_dec>0 else 0
        whip=round((h+bb)/ip_dec,3) if ip_dec>0 else 0
        _wp.append({'name':nm,'team':tm,'ip':ip_disp,'ip_dec':ip_dec,'k':round(k,1),
                    'qs':round(qs,1),'sv':round(sv,1),'hd':round(hd,1),'era':era,'whip':whip,'ptype':'pit'})
    weekly_top_pitchers=zscore_players(_wp,PIT_CATS,lower_better={'era','whip'},min_key='ip_dec',min_val=1,ip_weight='ip_dec')[:10]
    for i,p in enumerate(weekly_top_pitchers): p['rank']=i+1; p['score']=round(p['z_total'],2); p['week']=_latest_week

# ── Players ───────────────────────────────────────────────────────────────────
cursor.execute("""
    SELECT player_name,
        (SELECT team_name FROM player_snapshots p2 WHERE p2.player_name=p.player_name AND p2.player_type='batter' ORDER BY snapshot_date DESC LIMIT 1),
        SUM(CASE WHEN h_ab LIKE '%/%' AND h_ab!='--/--' THEN CAST(SUBSTR(h_ab,1,INSTR(h_ab,'/')-1) AS REAL) ELSE 0 END),
        SUM(CASE WHEN h_ab LIKE '%/%' AND h_ab!='--/--' THEN CAST(SUBSTR(h_ab,INSTR(h_ab,'/')+1) AS REAL) ELSE 0 END),
        SUM(COALESCE(r,0)),SUM(COALESCE(hr,0)),SUM(COALESCE(rbi,0)),SUM(COALESCE(bb,0)),SUM(COALESCE(sb,0)),
        SUM(CASE WHEN h_ab LIKE '%/%' AND h_ab!='--/--' AND ops IS NOT NULL
            THEN (ops-(CAST(SUBSTR(h_ab,1,INSTR(h_ab,'/')-1) AS REAL)+COALESCE(bb,0))
                 /NULLIF(CAST(SUBSTR(h_ab,INSTR(h_ab,'/')+1) AS REAL)+COALESCE(bb,0),0))
                 *CAST(SUBSTR(h_ab,INSTR(h_ab,'/')+1) AS REAL) ELSE 0 END)
    FROM player_snapshots p WHERE player_type='batter' AND player_name NOT IN ('Empty','__Empty__')
    GROUP BY player_name
    HAVING SUM(CASE WHEN h_ab LIKE '%/%' AND h_ab!='--/--' THEN CAST(SUBSTR(h_ab,INSTR(h_ab,'/')+1) AS REAL) ELSE 0 END)>=50
""")
batters=[]
for row in cursor.fetchall():
    name,team,h,ab,r,hr,rbi,bb,sb,tb=row
    if not team: continue
    avg=h/ab if ab>0 else 0; obp=(h+bb)/(ab+bb) if (ab+bb)>0 else 0
    slg=tb/ab if ab>0 else 0; ops=obp+slg
    batters.append({'name':name,'team':team,'ab':int(ab),'r':round(r,1),'hr':round(hr,1),'rbi':round(rbi,1),'sb':round(sb,1),'avg':round(avg,3),'ops':round(ops,3),'ptype':'bat'})

cursor.execute("""
    SELECT player_name,
        (SELECT team_name FROM player_snapshots p2 WHERE p2.player_name=p.player_name AND p2.player_type='pitcher' ORDER BY snapshot_date DESC LIMIT 1),
        SUM(ip),SUM(COALESCE(h,0)),SUM(COALESCE(er,0)),SUM(COALESCE(bb,0)),
        SUM(COALESCE(k,0)),SUM(COALESCE(qs,0)),SUM(COALESCE(sv,0)),SUM(COALESCE(hd,0))
    FROM player_snapshots p WHERE player_type='pitcher' AND ip IS NOT NULL AND ip>0
      AND player_name NOT IN ('Empty','__Empty__')
    GROUP BY player_name HAVING SUM(ip)>=10
""")
pitchers=[]
for row in cursor.fetchall():
    name,team,ip,h,er,bb,k,qs,sv,hd=row
    if not team: continue
    ip_dec=parse_ip(ip)
    ip_disp=f"{int(ip_dec)}.{round((ip_dec-int(ip_dec))*3)}"
    era=round((er/ip_dec)*9,2) if ip_dec>0 else 0
    whip=round((h+bb)/ip_dec,3) if ip_dec>0 else 0
    pitchers.append({'name':name,'team':team,'ip':ip_disp,'ip_dec':ip_dec,'k':round(k,1),'qs':round(qs,1),'sv':round(sv,1),'hd':round(hd,1),'era':era,'whip':whip,'ptype':'pit'})

conn.close()

batters=zscore_players(batters,BAT_CATS,min_key='ab',min_val=50)
pitchers=zscore_players(pitchers,PIT_CATS,lower_better={'era','whip'},min_key='ip_dec',min_val=10,ip_weight='ip_dec')
all_players=batters+pitchers

all_batters_ranked=zscore_players([dict(b) for b in batters],BAT_CATS,min_key='ab',min_val=50)
all_pitchers_ranked=zscore_players([dict(p) for p in pitchers],PIT_CATS,lower_better={'era','whip'},min_key='ip_dec',min_val=10,ip_weight='ip_dec')
for i,b in enumerate(all_batters_ranked): b['rank']=i+1; b['score']=round(b['z_total'],2)
for i,p in enumerate(all_pitchers_ranked): p['rank']=i+1; p['score']=round(p['z_total'],2)

top_batters=all_batters_ranked[:10]
top_pitchers=all_pitchers_ranked[:10]
for x in top_batters+top_pitchers:
    for cat in (BAT_CATS if x['ptype']=='bat' else PIT_CATS):
        x[f'z_{cat}']=round(x.get(f'z_{cat}',0),2)

team_players=defaultdict(list)
for p in all_players: team_players[p['team']].append(p)

team_bat=defaultdict(list); team_pit=defaultdict(list)
for b in all_batters_ranked: team_bat[b['team']].append(b)
for p in all_pitchers_ranked: team_pit[p['team']].append(p)

# Rosters for trade evaluator
team_rosters=defaultdict(lambda:{'batters':[],'pitchers':[]})
for b in all_batters_ranked:
    entry={'name':b['name'],'ptype':'bat','z_total':round(b['z_total'],2)}
    for c in BAT_CATS: entry[f'z_{c}']=round(b.get(f'z_{c}',0),2)
    team_rosters[b['team']]['batters'].append(entry)
for p in all_pitchers_ranked:
    entry={'name':p['name'],'ptype':'pit','z_total':round(p['z_total'],2)}
    for c in PIT_CATS: entry[f'z_{c}']=round(p.get(f'z_{c}',0),2)
    team_rosters[p['team']]['pitchers'].append(entry)

# Trades
teams_ranked=sorted(team_avg_z.keys(),key=lambda t:-sum(team_avg_z[t].values()))
trades_data=[]
used_players=set()
for team in teams_ranked:
    tz=team_avg_z[team]
    weak_cats=[c for c,z in sorted(tz.items(),key=lambda x:x[1])[:4] if z<0.4]
    strong_cats=[c for c,_ in sorted(tz.items(),key=lambda x:-x[1])[:3]]
    team_trades=[]; local_used=set()
    for weak_cat in weak_cats[:2]:
        result=find_best_trade(team,weak_cat,team_avg_z,all_players,team_players,used_players|local_used)
        if not result: continue
        inc,outs,partner,gain=result
        local_used.add(inc['name'])
        for o in outs: local_used.add(o['name'])
        out_z=sum(o['z_total'] for o in outs); val_diff=round(inc['z_total']-out_z,2)
        partner_z=team_avg_z.get(partner,{})
        partner_needs=[c for c,z in sorted(partner_z.items(),key=lambda x:x[1])[:2] if z<0.5]
        team_trades.append({'weak_cat':weak_cat.upper(),'partner':partner,'is_package':len(outs)>1,
            'get':{'name':inc['name'],'z_cat':round(inc[f'z_{weak_cat}'],2),'z_total':round(inc['z_total'],2)},
            'give':[{'name':o['name'],'z_total':round(o['z_total'],2)} for o in outs],
            'give_z_total':round(out_z,2),'val_diff':val_diff,'is_fair':abs(val_diff)<=1.0,
            'partner_gains':[c.upper() for c in partner_needs[:2]],'gain':round(gain,2)})
    trades_data.append({'team':team,
        'weaknesses':[{'cat':c.upper(),'z':round(tz[c],2)} for c in weak_cats[:3]],
        'strengths':[{'cat':c.upper(),'z':round(tz[c],2)} for c in strong_cats],
        'trades':team_trades})

# ── Assemble data ─────────────────────────────────────────────────────────────
from datetime import date
snap_date = date.today().strftime('%Y-%m-%d')

weekly_writeups = {}
_wu_path = os.path.join(script_dir, 'weekly_writeups.json')
if os.path.exists(_wu_path):
    with open(_wu_path) as _f:
        try:
            weekly_writeups = json.load(_f)
        except Exception:
            pass

data={'snap_date':snap_date,'standings':[],'top_batters':top_batters,'top_pitchers':top_pitchers,
      'weekly_top_batters':weekly_top_batters,'weekly_top_pitchers':weekly_top_pitchers,
      'teams':{},'weekly_exp':{},'actual_by_week':actual_by_week,'trades':trades_data,
      'rosters':{team:dict(v) for team,v in team_rosters.items()},
      'weekly_writeups':weekly_writeups}

for team in exp_order:
    ew=exp_wins[team]; el=exp_losses[team]; epct=round(ew/(ew+el),3) if (ew+el)>0 else 0
    a=actual.get(team,{}); diff=round(a.get('pct',0)-epct,3)
    data['standings'].append({'team':team,'owner':a.get('owner',''),
        'exp_w':round(ew,1),'exp_l':round(el,1),'exp_pct':epct,
        'act_w':a.get('w',0),'act_l':a.get('l',0),'act_t':a.get('t',0),'act_pct':round(a.get('pct',0),3),'diff':diff,
        'r':int(a.get('r',0)),'hr':int(a.get('hr',0)),'rbi':int(a.get('rbi',0)),'sb':int(a.get('sb',0)),
        'avg':round(a.get('avg',0),3),'ops':round(a.get('ops',0),3),'k':int(a.get('k',0)),'qs':int(a.get('qs',0)),
        'sv':int(a.get('sv',0)),'hd':int(a.get('hd',0)),'era':round(a.get('era',0),3),'whip':round(a.get('whip',0),3)})
    data['teams'][team]={'batters':team_bat.get(team,[])[:10],'pitchers':team_pit.get(team,[])[:10]}
    data['weekly_exp'][team]=weekly_exp.get(team,[])

# ── Inject into HTML ──────────────────────────────────────────────────────────
with open(html_template) as f:
    html=f.read()

html=re.sub(r'const DATA = \{.*?\};', f'const DATA = {json.dumps(data)};', html, flags=re.DOTALL)

with open(html_template,'w') as f:
    f.write(html)

# Also write JSON separately
with open(os.path.join(script_dir,'dashboard_data.json'),'w') as f:
    json.dump(data,f)

print(f"Dashboard regenerated — {len(html):,} bytes, snap_date={snap_date}")
