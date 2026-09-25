import copy
import pytest
from ega.config import ExperimentConfig
from ega.data.synthetic import make_demo
from ega.simulator import InventoryEnvironment
from ega.forecasting.core import SeasonalForecaster
from ega.experiment import sources_for,true_problem_for

@pytest.fixture
def config():
    return ExperimentConfig.model_validate({'start_day':140,'days':4,'warmup_days':2,
        'solver':{'horizon':6,'scenarios':3,'time_limit':10},
        'forecast':{'deep_epochs':1,'hidden_size':8,'max_training_windows':32,'lgbm_estimators':3}})

@pytest.fixture
def panel():return make_demo(items=1,stores=2,days=180)

@pytest.fixture
def env(panel,config):
    e=InventoryEnvironment(panel,140,7,'test',config);e.begin_day(140);return e

@pytest.fixture
def snapshot(env,config):return env.snapshot(config.forecast.lookback)

@pytest.fixture
def model(panel,config):return SeasonalForecaster(config.forecast).fit(panel,138)

@pytest.fixture
def docs(env,config):return sources_for(env,config,'normal',False)[0]

@pytest.fixture
def problem(snapshot,docs,model,config):return true_problem_for(snapshot,docs,model,config,7)
