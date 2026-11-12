import pandas as pd
import pytest
from creatorlab.engine import validate, train_model, recommend

def test_missing_columns():
    with pytest.raises(ValueError):
        validate(pd.DataFrame({'views':[5]}))

def test_recommendation():
    df = pd.DataFrame([dict(role='A', format='cosplay', hook='closeup', duration_sec=12, publish_hour=19, views=100, likes=10, comments=1, shares=1, new_followers=2)])
    cleaned = validate(df)
    assert cleaned.iloc[0]['engagement_rate'] == .12
    assert recommend(cleaned).iloc[0]['role'] == 'A'
    assert train_model(cleaned)[0] is None
