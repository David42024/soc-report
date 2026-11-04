from pathlib import Path
import json, sys
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE/'plot-libs'))
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

D=json.loads((HERE/'simulation-results.json').read_text())
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.titlesize':10,
    'axes.labelsize':9,'legend.fontsize':8,'xtick.labelsize':8,'ytick.labelsize':8,
    'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42,'svg.fonttype':'none'})
BLUE, GREEN, ORANGE, GRAY = '#245675','#18735d','#b45a25','#53616a'
COL=[GRAY,ORANGE,GREEN]
def save(fig, number):
    for ext in ['png','pdf','svg']:
        fig.savefig(HERE/f'figure-{number}.{ext}',dpi=320,bbox_inches='tight',facecolor='white')
    plt.close(fig)
def box(ax,x,y,w,h,text,color=BLUE,fill='#f3f6f8',size=9):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.012,rounding_size=0.025',
        lw=1,ec=color,fc=fill))
    ax.text(x+w/2,y+h/2,text,ha='center',va='center',fontsize=size,color='#111111',linespacing=1.4)
def arrow(ax,start,end,text=None,offset=(0,0)):
    ax.annotate('',xy=end,xytext=start,arrowprops=dict(arrowstyle='->',color=GRAY,lw=1.2))
    if text: ax.text((start[0]+end[0])/2+offset[0],(start[1]+end[1])/2+offset[1],text,
        ha='center',va='center',fontsize=8,backgroundcolor='white')

# 1. Actual artifact architecture with an explicit inference trust boundary.
fig,ax=plt.subplots(figsize=(6.1,3.9));ax.set(xlim=(0,1),ylim=(0,1));ax.axis('off')
ax.add_patch(Rectangle((.01,.02),.98,.77,fill=False,ec=GRAY,lw=1,ls='--'))
ax.text(.025,.76,'LOCAL HOST  |  Data and workflow state',fontsize=9,weight='bold')
box(ax,.24,.87,.52,.1,'Hosted models  |  Groq → Gemini',ORANGE,'#fff7f0')
box(ax,.04,.55,.27,.12,'React UI\nRoles and sessions')
box(ax,.39,.55,.23,.12,'FastAPI\nPolicy checks')
box(ax,.72,.55,.24,.12,'Langflow\nLLM classification')
box(ax,.05,.27,.26,.12,'PostgreSQL 16\nReports and audit',GREEN,'#f0f7f4')
box(ax,.40,.27,.23,.12,'n8n\nTeam and notice')
box(ax,.72,.27,.24,.12,'Redis 7\nQueue and cache')
box(ax,.23,.05,.55,.10,'Business events  +  audit_log',GREEN,'#f0f7f4')
arrow(ax,(.31,.61),(.39,.61));arrow(ax,(.62,.61),(.72,.61))
arrow(ax,(.84,.67),(.67,.87),'Report text',(.075,-.015))
arrow(ax,(.43,.55),(.24,.39),'1 Commit',(-.015,.0))
ax.annotate('',xy=(.51,.39),xytext=(.51,.55),arrowprops=dict(arrowstyle='<->',color=GRAY,lw=1.2))
ax.text(.53,.47,'2 Dispatch\nand callbacks',ha='left',va='center',fontsize=8,backgroundcolor='white')
arrow(ax,(.62,.55),(.79,.39),'Retry',(.155,-.025))
arrow(ax,(.18,.27),(.34,.15));arrow(ax,(.51,.27),(.51,.15))
ax.text(.5,.82,'Only inference crosses the local boundary',ha='center',fontsize=8,color=ORANGE)
save(fig,1)

# 2. Actual ordering. Classification does precede the database commit.
fig,ax=plt.subplots(figsize=(6.1,3.9));ax.axis('off');ax.set(xlim=(0,1),ylim=(0,1))
roles=[('Client',.07),('FastAPI',.29),('Langflow',.51),('PostgreSQL',.73),('n8n',.94)]
for label,x in roles:
    ax.text(x,.98,label,ha='center',va='top',weight='bold',fontsize=9)
    ax.plot([x,x],[.08,.93],color='#cccccc',lw=.8,ls='--')
steps=[(.89,.07,.29,'Submit report + UUID'),(.78,.29,.51,'Classify or conservative fallback'),
    (.66,.29,.73,'Commit report and policy version'),(.54,.29,.94,'Webhook with report identifier'),
    (.42,.94,.29,'Fetch context and validate pinned rules'),(.30,.94,.29,'Assignment and initial notice'),
    (.18,.29,.07,'Receipt / pending')]
for y,a,b,label in steps:
    arrow(ax,(a,y),(b,y));ax.text((a+b)/2,y+.027,label,ha='center',fontsize=8,
        bbox=dict(facecolor='white',edgecolor='none',pad=.5))
ax.text(.5,.025,'Timeout → pending event → Redis retry or PostgreSQL reconciliation',ha='center',fontsize=8,color=GREEN)
save(fig,2)

# 3. Separate evidence streams; a simulation never becomes an operational sample.
fig,ax=plt.subplots(figsize=(6.1,3.3));ax.axis('off');ax.set(xlim=(0,1),ylim=(0,1))
box(ax,.05,.77,.90,.16,'Research questions\nDurability and conditional benefit',size=9)
box(ax,.04,.48,.43,.17,'A  Software evidence\nCode and archived tests',BLUE)
box(ax,.54,.48,.42,.17,'B  Synthetic scenarios\n2,400 generated cases',ORANGE,'#fff7f0')
arrow(ax,(.25,.77),(.25,.65));arrow(ax,(.75,.77),(.75,.65))
box(ax,.04,.19,.43,.17,'74 local + 22 earlier live checks\nFunctional assertions',BLUE,size=8)
box(ax,.54,.19,.42,.17,'Bootstrap and sensitivity\nConditional effects',ORANGE,'#fff7f0',size=8)
arrow(ax,(.25,.48),(.25,.36));arrow(ax,(.75,.48),(.75,.36))
ax.text(.5,.07,'Simulation is not operational evidence',ha='center',fontsize=9,weight='bold')
save(fig,3)

# 4. Coverage-risk curves under useful vs uninformative confidence.
fig,ax=plt.subplots(figsize=(6.1,3.55))
for rows,color,mark,label in [(D['thresholds'],GREEN,'o','Confidence informative by assumption'),
    (D['shifted'],ORANGE,'s','Confidence shuffled')]:
    ax.plot([r['coverage']*100 for r in rows],[r['risk']*100 for r in rows],
        color=color,marker=mark,lw=1.5,label=label)
r=D['main'];ax.annotate('τ = 0.75',xy=(r['coverage']*100,r['risk']*100),
    xytext=(r['coverage']*100-26,r['risk']*100-2.6),arrowprops=dict(arrowstyle='->',color=GREEN),fontsize=9)
ax.set(xlabel='Cases accepted without review (%)',ylabel='Type error among accepted cases (%)',ylim=(0,16))
ax.grid(alpha=.2);ax.legend(loc='upper left',frameon=False,fontsize=8)
ax.set_title('SYNTHETIC  |  Thresholds do not guarantee a risk level',loc='left',fontsize=9)
save(fig,4)

# 5. Effect sizes, denominators and uncertainty distinguish active work from elapsed time.
fig,axs=plt.subplots(1,2,figsize=(6.1,3.5),gridspec_kw={'width_ratios':[.95,1.05]})
names=list(D['policies'])
vals=[D['policies'][x]['active_mean'] for x in names]
axs[0].bar(names,vals,color=COL,width=.62)
for i,v in enumerate(vals):axs[0].text(i,v+.3,f'{v:.2f}',ha='center',fontsize=8)
axs[0].set(ylabel='Mean active human time (min/case)',ylim=(0,16))
axs[0].set_title('(a) Assumed work model',loc='left',fontsize=9)
e=D['effects'];vals=[e['response_pp'],e['resolution_pp']];cis=[e['response_ci'],e['resolution_ci']]
for i,(v,ci) in enumerate(zip(vals,cis)):
    axs[1].errorbar(v,i,xerr=[[v-ci[0]],[ci[1]-v]],fmt='o',color=GREEN,capsize=4)
    axs[1].text(v,i+.17,f'{v:.2f} [{ci[0]:.2f}, {ci[1]:.2f}]',ha='center',fontsize=7.5)
axs[1].set(yticks=[0,1],yticklabels=['Response','Resolution'],xlabel='SLA change (percentage points)',
    ylim=(-.5,1.65),xlim=(0,35));axs[1].set_title('(b) Guarded versus manual',loc='left',fontsize=9)
axs[1].grid(axis='x',alpha=.2)
fig.suptitle('SYNTHETIC  |  2,400 paired cases; 95% percentile bootstrap intervals',fontsize=9)
fig.tight_layout(w_pad=1.1);save(fig,5)

# 6. Two failure mechanisms: reviewer wait and unbounded fluid backlog.
fig,axs=plt.subplots(1,2,figsize=(6.1,3.6))
cap=D['reviewer_capacity']
axs[0].plot([r['extra_minutes'] for r in cap],[r['response']*100 for r in cap],'-o',color=GREEN)
axs[0].axhline(D['policies']['Manual']['response']*100,color=GRAY,ls='--',lw=1,label='Manual scenario')
axs[0].set(xlabel='Extra wait for referred cases (min)',ylabel='Response SLA met (%)',ylim=(45,100))
axs[0].legend(frameon=False,fontsize=7.5,loc='lower left');axs[0].set_title('(a) Review capacity sensitivity',loc='left',fontsize=9)
for rec,col in zip(D['recovery'],[GREEN,BLUE,ORANGE]):
    axs[1].plot(np.arange(121),rec['backlog'],color=col,label=f"λ = {rec['arrivals_per_min']}/min")
axs[1].axvspan(0,30,color='#dce4e9',alpha=.5)
axs[1].text(16,1050,'Outage',rotation=90,ha='center',fontsize=7.5)
axs[1].set(xlabel='Simulated time (min)',ylabel='Pending cases',ylim=(0,1800))
axs[1].legend(frameon=False,fontsize=7.5,loc='upper left');axs[1].set_title('(b) Assumed service μ = 20/min',loc='left',fontsize=9)
for ax in axs:ax.grid(alpha=.15)
fig.suptitle('SYNTHETIC  |  Recovery requires available capacity',fontsize=9)
fig.tight_layout(w_pad=1.2);save(fig,6)
print('Generated six figures in PNG, PDF and SVG')
