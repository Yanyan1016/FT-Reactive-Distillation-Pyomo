'''
How to Train Your Dragon: V1
Sequentially initialize FT reactive distillation model automatically
'''
# system imports
import sys
import os
import datetime
sys.path.append(os.path.abspath('..'))
sys.path.append(os.path.abspath('../..'))

# sys.path.append(os.path.abspath('../..'))
import numpy as np
from matplotlib import pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

import pickle
import dill
from copy import deepcopy

# pyomo imports
from pyomo import environ as pe
from global_sets.component import m

from stages.reactive_stage import reactive_stage_rule
from stages.condenser_stage import condenser_stage_rule
from stages.reboiler_stage import reboiler_stage_rule

from utility.display_utility import trans_product_mole, trans_product_mass, beautify, \
                                    beautify_reactive, HiddenLogs, plot_distribution
from utility.model_utility import add_dual, update_dual, delete_dual, check_DOF, check_violate_constraint
from utility.data_utility import cal_cnumber

'''
Constructing the model based on mode inputs
'''

model = pe.ConcreteModel(name='reactive_distillation')
logname = datetime.datetime.now().strftime('%Y%m%d_%Hh%Mm%Ss')
log_text_dir = './log/text/'+logname+'.dat'
log_figure_dir = './log/figure/'+logname+'.pdf'

'''
model input
'''
tray_number = 10
non_reactive_flag = [1,2,3,4,10]
# non_reactive_flag = []
side_draw_flag = {4:0.2,7:0.7}
# default temperature is
temperature_flag = {6:240,7:240,8:245,9:250}
rr_ratio = 0.05

model.TRAY = pe.RangeSet(1,tray_number)
model.TRAY_nonreactive = pe.Set(initialize=non_reactive_flag)
model.TRAY_reactive = model.TRAY - model.TRAY_nonreactive

model.reactive = pe.Block(model.TRAY,rule=reactive_stage_rule)
add_dual(pe,model)

# in/out variable
for j in model.reactive:
    model.reactive[j].x_.fix(0)
    model.reactive[j].y_.fix(0)
    model.reactive[j].L['in'].fix(0)
    model.reactive[j].V['in'].fix(0)
    model.reactive[j].H_L_.fix(0)
    model.reactive[j].H_V_.fix(0)

# operating parameters
for j in model.reactive:
    model.reactive[j].cat.fix(3000)
    model.reactive[j].P.fix(20)
    model.reactive[j].VLE_block.n_ave.fix(20)

    model.reactive[j].F.fix(1)
    model.reactive[j].T_F.fix(200+273.15)
    model.reactive[j].z['CO'].fix(1/(1+2)-0/2)
    model.reactive[j].z['H2'].fix(2/(1+2)-0/2)
    model.reactive[j].z['C30H62'].fix(0)

    model.reactive[j].PR_L.fix(1)
    model.reactive[j].PR_V.fix(1)

    # model.reactive[j].Q_main.fix(0)
    model.reactive[j].T.setub(220+273.15)
    model.reactive[j].T.setlb(200+273.15)

model.obj = pe.Objective(expr = sum(model.reactive[j].T - model.reactive[j].MPCC.pf \
                                    for j in model.reactive),sense=pe.maximize)

opt = pe.SolverFactory('ipopt')

opt.options['print_user_options'] = 'yes'
opt.options['linear_solver'] = 'ma86'

opt.options['linear_system_scaling '] = 'mc19'
opt.options['linear_scaling_on_demand '] = 'no'

opt.options['max_iter'] = 7000

results = opt.solve(model,tee=False)
update_dual(pe,model)

print('\nFirst Solve, disconnected reactive stages')
print('-'*108)
beautify_reactive(pe,model)

def V_between_rule(model,j):
    if j == model.TRAY.last(): return pe.Constraint.Skip
    return model.reactive[j].V['in'] == model.reactive[j+1].V['out']
model.V_between_con = pe.Constraint(model.TRAY,rule=V_between_rule)

def Vy_between_rule(model,j,i):
    if j == model.TRAY.last(): return pe.Constraint.Skip
    return model.reactive[j].y_['in',i] == model.reactive[j+1].y[i]
model.Vy_between_con = pe.Constraint(model.TRAY,m.COMP_TOTAL,rule=Vy_between_rule)

def Vh_between_rule(model,j):
    if j == model.TRAY.last(): return pe.Constraint.Skip
    return model.reactive[j].H_V_['in'] == model.reactive[j+1].H_V
model.Vh_between_con = pe.Constraint(model.TRAY,rule=Vh_between_rule)

def L_between_rule(model,j):
    if j == model.TRAY.last(): return pe.Constraint.Skip
    return model.reactive[j+1].L['in'] == model.reactive[j].L['out']
model.L_between_con = pe.Constraint(model.TRAY,rule=L_between_rule)

def Lx_between_rule(model,j,i):
    if j == model.TRAY.last(): return pe.Constraint.Skip
    return model.reactive[j+1].x_['in',i] == model.reactive[j].x[i]
model.Ly_between_con = pe.Constraint(model.TRAY,m.COMP_TOTAL,rule=Lx_between_rule)

def Lh_between_rule(model,j):
    if j == model.TRAY.last(): return pe.Constraint.Skip
    return model.reactive[j+1].H_L_['in'] == model.reactive[j].H_L
model.Lh_between_con = pe.Constraint(model.TRAY,rule=Lh_between_rule)

for j in model.reactive:
    if j != model.TRAY.first():
        model.reactive[j].x_.unfix()
        model.reactive[j].H_L_.unfix()
        model.reactive[j].L['in'].unfix()
    if j != model.TRAY.last():
        model.reactive[j].y_.unfix()
        model.reactive[j].V['in'].unfix()
        model.reactive[j].H_V_.unfix()

opt.options['warm_start_init_point'] = 'yes'
opt.options['warm_start_bound_push'] = 1e-20
opt.options['warm_start_mult_bound_push'] = 1e-20
opt.options['mu_init'] = 1e-6

results = opt.solve(model,tee=False)
update_dual(pe,model)


PR_range = np.linspace(1,0,11)
print('\nConnect stages and introduce inter-stage flow')
for r in PR_range:
    for j in model.reactive:
        model.reactive[j].PR_L.fix(r)
        model.reactive[j].PR_V.fix(r)

    results = opt.solve(model,tee=False)
    update_dual(pe,model)
    print('\n>','Working on PR ratio = {:.2f}'.format(r))
    print('-'*108)
    beautify_reactive(pe,model)

for j in model.TRAY_nonreactive:

    model.reactive[j].T.unfix()
    model.reactive[j].Q_main.fix(0)
    model.reactive[j].cat.fix(0)
    model.reactive[j].F.fix(0)

    results = opt.solve(model,tee=False)
    update_dual(pe,model)

    print('\n>','Working to remove catalyst and feed from stage {}, unfixing temperature, changing to adiabatic:'.format(j))
    print('-'*108)
    beautify_reactive(pe,model)

for i in model.block_data_objects():
    if i.name != 'reactive_distillation':
        i.deactivate()
for i in model.component_objects(pe.Constraint, active=True):
    i.deactivate()

model.condenser = pe.Block(rule=condenser_stage_rule)

# in/out variables
model.condenser.x_.fix(0)
for i in m.COMP_TOTAL:
    model.condenser.y_['in',i].fix(model.reactive[model.TRAY.first()].y[i].value)
model.condenser.V['in'].fix(model.reactive[model.TRAY.first()].V['out'].value)
model.condenser.L['in'].fix(0)
model.condenser.V['P'].fix(0)
model.condenser.H_L_.fix(0)
model.condenser.H_V_.fix(model.reactive[model.TRAY.first()].H_V.value)

# operating parameters
model.condenser.P.fix(19)
model.condenser.T_F.fix(200+273.15)
model.condenser.F.fix(0)
model.condenser.z.fix(0)
model.condenser.VLE_block.n_ave.fix(4)
model.condenser.PR_L.fix(1)

model.condenser.T.setub(30+273.15)

model.del_component(model.obj)
model.obj = pe.Objective(expr = model.condenser.T, sense = pe.maximize)

delete_dual(pe,model)
add_dual(pe,model)

results = opt.solve(model,tee=False)
update_dual(pe,model)

model.condenser.deactivate()
check_DOF(pe,model)

model.reboiler = pe.Block(rule=reboiler_stage_rule)

# in/out variables
model.reboiler.y_.fix(0)
for i in m.COMP_TOTAL:
    model.reboiler.x_['in',i].fix(model.reactive[model.TRAY.last()].x[i].value)
model.reboiler.L['in'].fix(model.reactive[model.TRAY.last()].L['out'].value)
model.reboiler.V['in'].fix(0)
model.reboiler.L['P'].fix(0)
model.reboiler.V['P'].fix(0)
model.reboiler.H_L_.fix(model.reactive[model.TRAY.last()].H_L.value)
model.reboiler.H_V_.fix(0)

# operating parameters
model.reboiler.P.fix(20)
model.reboiler.T_F.fix(200+273.15)
model.reboiler.F.fix(0)
model.reboiler.z.fix(0)
model.reboiler.VLE_block.n_ave.fix(20)

model.reboiler.T.setub(model.reactive[model.TRAY.last()].T.value)

model.del_component(model.obj)
model.obj = pe.Objective(expr = model.reboiler.T - model.reboiler.MPCC.pf, sense = pe.maximize)

delete_dual(pe,model)
add_dual(pe,model)

results = opt.solve(model,tee=False)
update_dual(pe,model)

for i in model.block_data_objects():
    if i.name != 'reactive_distillation':
        i.activate()
for i in model.component_objects(pe.Constraint):
    i.activate()

def V_condenser_rule(model):
    return model.reactive[model.TRAY.first()].V['out'] == model.condenser.V['in']
model.V_condenser_con = pe.Constraint(rule=V_condenser_rule)

def Vy_condenser_rule(model,i):
    return model.reactive[model.TRAY.first()].y[i] == model.condenser.y_['in',i]
model.Vy_condenser_con = pe.Constraint(m.COMP_TOTAL,rule=Vy_condenser_rule)

def Vh_condenser_rule(model):
    return model.reactive[model.TRAY.first()].H_V == model.condenser.H_V_['in']
model.Vh_condenser_con = pe.Constraint(rule=Vh_condenser_rule)

def L_condenser_rule(model):
    return model.reactive[model.TRAY.first()].L['in'] == model.condenser.L['out']
model.L_condenser_con = pe.Constraint(rule=L_condenser_rule)

def Lx_condenser_rule(model,i):
    return model.reactive[model.TRAY.first()].x_['in',i] == model.condenser.x[i]
model.Lx_condenser_con = pe.Constraint(m.COMP_TOTAL,rule=Lx_condenser_rule)

def Lh_condenser_rule(model):
    return model.reactive[model.TRAY.first()].H_L_['in'] == model.condenser.H_L
model.Lh_condenser_con = pe.Constraint(rule=Lh_condenser_rule)

def V_reboiler_rule(model):
    return model.reactive[model.TRAY.last()].V['in'] == model.reboiler.V['out']
model.V_reboiler_con = pe.Constraint(rule=V_reboiler_rule)

def Vy_reboiler_rule(model,i):
    return model.reactive[model.TRAY.last()].y_['in',i] == model.reboiler.y[i]
model.Vy_reboiler_con = pe.Constraint(m.COMP_TOTAL,rule=Vy_reboiler_rule)

def Vh_reboiler_rule(model):
    return model.reactive[model.TRAY.last()].H_V_['in'] == model.reboiler.H_V
model.Vh_reboiler_con = pe.Constraint(rule=Vh_reboiler_rule)

def L_reboiler_rule(model):
    return model.reactive[model.TRAY.last()].L['out'] + 1e-6 == model.reboiler.L['in']
model.L_reboiler_con = pe.Constraint(rule=L_reboiler_rule)

def Lx_reboiler_rule(model,i):
    return model.reactive[model.TRAY.last()].x[i] == model.reboiler.x_['in',i]
model.Lx_reboiler_con = pe.Constraint(m.COMP_TOTAL,rule=Lx_reboiler_rule)

def Lh_reboiler_rule(model):
    return model.reactive[model.TRAY.last()].H_L == model.reboiler.H_L_['in']
model.Lh_reboiler_con = pe.Constraint(rule=Lh_reboiler_rule)

model.del_component(model.obj)
model.obj = pe.Objective(expr = sum(model.reactive[j].T - model.reactive[j].MPCC.pf for j in model.TRAY_reactive)\
                        + sum( - model.reactive[j].MPCC.pf for j in model.TRAY_nonreactive) - model.reboiler.MPCC.pf ,sense=pe.maximize)

delete_dual(pe,model)
add_dual(pe,model)

# in/out variables
model.condenser.x_.fix(0)
for i in m.COMP_TOTAL:
    model.condenser.y_['in',i].unfix()
model.condenser.V['in'].unfix()
model.condenser.L['in'].fix(0)
model.condenser.V['P'].fix(0)
model.condenser.H_L_.fix(0)
model.condenser.H_V_.unfix()

# operating parameters
model.condenser.P.fix(19)
model.condenser.T_F.fix(200+273.15)
model.condenser.F.fix(0)
model.condenser.z.fix(0)
model.condenser.VLE_block.n_ave.fix(4)
model.condenser.PR_L.fix(1)

model.condenser.T.fix(30+273.15)

# in/out variables
model.reboiler.y_.fix(0)
for i in m.COMP_TOTAL:
    model.reboiler.x_['in',i].unfix()
model.reboiler.L['in'].unfix()
model.reboiler.V['in'].fix(0)
model.reboiler.L['P'].fix(0)
model.reboiler.V['P'].fix(0)
model.reboiler.H_L_.unfix()
model.reboiler.H_V_.fix(0)

# operating parameters
model.reboiler.P.fix(20)
model.reboiler.T_F.fix(200+273.15)
model.reboiler.F.fix(0)
model.reboiler.z.fix(0)
model.reboiler.VLE_block.n_ave.fix(20)

model.reboiler.T.fix(model.reactive[model.TRAY.last()].T.value)

# unlock reflux and reboiler vapor
for j in model.reactive:
    model.reactive[j].x_.unfix()
    model.reactive[j].H_L_.unfix()
    model.reactive[j].L['in'].unfix()
    model.reactive[j].y_.unfix()
    model.reactive[j].V['in'].unfix()
    model.reactive[j].H_V_.unfix()

for j in model.reactive:
    if j in model.TRAY_reactive:
        model.reactive[j].cat.fix(3000)
        model.reactive[j].P.fix(20)
        model.reactive[j].VLE_block.n_ave.fix(20)

        model.reactive[j].F.fix(1)
        model.reactive[j].T_F.fix(200+273.15)
        model.reactive[j].z['CO'].fix(1/(1+2)-0/2)
        model.reactive[j].z['H2'].fix(2/(1+2)-0/2)
        model.reactive[j].z['C30H62'].fix(0)

        model.reactive[j].PR_L.fix(0)
        model.reactive[j].PR_V.fix(0)

        # model.reactive[j].Q_main.fix(0)
        model.reactive[j].T.setub(220+273.15)
        model.reactive[j].T.setlb(200+273.15)

    elif j in model.TRAY_nonreactive:
        model.reactive[j].cat.fix(0)
        model.reactive[j].P.fix(20)
        model.reactive[j].VLE_block.n_ave.fix(20)

        model.reactive[j].F.fix(0)
        model.reactive[j].T_F.fix(200+273.15)
        model.reactive[j].z['CO'].fix(1/(1+2)-0/2)
        model.reactive[j].z['H2'].fix(2/(1+2)-0/2)
        model.reactive[j].z['C30H62'].fix(0)

        model.reactive[j].PR_L.fix(0)
        model.reactive[j].PR_V.fix(0)

        model.reactive[j].Q_main.fix(0)
        model.reactive[j].T.setub(350+273.15)
        model.reactive[j].T.setlb(100+273.15)

results = opt.solve(model,tee=False)
update_dual(pe,model)

print('\nInitialized with no reflux and reboil complete')
beautify(pe,model)

PR_range = np.linspace(1,rr_ratio,10)
for r in PR_range:
    model.condenser.PR_L.fix(r)

    results = opt.solve(model,tee=False)
    update_dual(pe,model)

    print('\n>','Working on Reflux, PR ratio = {:.2f}'.format(r))
    print('-'*108)
    beautify(pe,model)

T_range = np.linspace(220+273.15,350+273.15,2)
for t in T_range:
    model.reboiler.T.fix(t)

    results = opt.solve(model,tee=False)
    update_dual(pe,model)
    print('\n>','Working on reboiler temperature = {:.2f}'.format(t))
    print('-'*108)
    beautify(pe,model)

for j in side_draw_flag.keys():

    r = side_draw_flag[j]
    model.reactive[j].PR_L.fix(r)

    results = opt.solve(model,tee=False)
    update_dual(pe,model)
    print('\n>','Working on side draw of {:.1%} on stage {}'.format(r,j))
    print('-'*108)
    beautify(pe,model)

for j in temperature_flag.keys():

    t = temperature_flag[j] + 273.15
    model.reactive[j].T.setub(t)

    results = opt.solve(model,tee=False)
    update_dual(pe,model)
    print('\n>','Working on adjusting stage {} temperature to {:.2f}C '.format(j,t-273.15))
    print('-'*108)
    beautify(pe,model)

print('Initialization Complete\nPlease check the logs for details')

plot_distribution(model)