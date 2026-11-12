import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

FEATURES = ['role', 'format', 'hook', 'duration_sec', 'publish_hour']
CATEGORICAL = ['role', 'format', 'hook']
NUMERIC = ['duration_sec', 'publish_hour']
REQUIRED = FEATURES + ['views', 'likes', 'comments', 'shares', 'new_followers']


def validate(df):
    missing = sorted(set(REQUIRED) - set(df.columns))
    if missing:
        raise ValueError('Missing columns: ' + ', '.join(missing))
    df = df.copy()
    for col in NUMERIC + ['views', 'likes', 'comments', 'shares', 'new_followers']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=NUMERIC + ['views'])
    df = df[(df['views'] >= 0) & (df['duration_sec'] > 0) & df['publish_hour'].between(0, 23)]
    if df.empty:
        raise ValueError('No valid video rows remain.')
    for col in ['likes', 'comments', 'shares', 'new_followers']:
        df[col] = df[col].fillna(0).clip(lower=0)
    df['engagement_rate'] = (df['likes'] + df['comments'] + df['shares']) / df['views'].clip(lower=1)
    df['follow_rate'] = df['new_followers'] / df['views'].clip(lower=1)
    return df


def train_model(df):
    if len(df) < 20:
        return None, 'Need at least 20 videos for exploratory modeling; more is strongly recommended.'
    pre = ColumnTransformer([
        ('cat', Pipeline([('fill', SimpleImputer(strategy='most_frequent')),
                          ('onehot', OneHotEncoder(handle_unknown='ignore'))]), CATEGORICAL),
        ('num', SimpleImputer(strategy='median'), NUMERIC),
    ])
    model = Pipeline([('pre', pre), ('model', RandomForestRegressor(n_estimators=120, min_samples_leaf=3, random_state=42))])
    model.fit(df[FEATURES], np.log1p(df['views']))
    return model, 'Exploratory model trained; predictions are associations, not causal effects.'


def recommend(df, model=None):
    rows = []
    overall = df['views'].median()
    for role in sorted(df['role'].dropna().unique()):
        sub = df[df['role'] == role]
        n = len(sub)
        median = float(sub['views'].median())
        # shrink sparse-category performance toward account-wide median
        score = (n * median + 5 * overall) / (n + 5)
        rows.append({'role': role, 'videos': n, 'median_views': int(median),
                     'shrunken_score': round(score), 'confidence': 'limited' if n < 5 else 'exploratory'})
    return pd.DataFrame(rows).sort_values('shrunken_score', ascending=False)


def experiment_suggestion(df):
    role = recommend(df).iloc[0]['role']
    return {'hypothesis': f'For {role}, a face-closeup opening may outperform a wide-shot opening on early retention.',
            'control': 'wide shot', 'variant': 'face closeup',
            'measurement': '3-second retention (if available), plus follows per 1,000 views',
            'caveat': 'Keep duration, posting window, and format comparable. Organic platform exposure is not randomized.'}
