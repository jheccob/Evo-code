import os
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import joblib


class AIModel:
    def __init__(self, model_path='data/ai_model.pkl', dataset_path='data/ai_training_data.csv'):
        self.model_path = model_path
        self.dataset_path = dataset_path
        self.model = None

        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)

        if os.path.exists(self.model_path):
            self.load()

    def _build_features(self, df):
        # assume df is indexed by timestamp and contains indicators
        if df is None or df.empty:
            raise ValueError('Dataframe vazio para features')

        row = df.iloc[-1]
        features = {
            'rsi': row.get('rsi', np.nan),
            'macd': row.get('macd', np.nan),
            'macd_signal': row.get('macd_signal', np.nan),
            'adx': row.get('adx', np.nan),
            'bb_width': row.get('bb_width', np.nan),
            'volume_ratio': row.get('volume_ratio', np.nan),
        }
        return pd.DataFrame([features])

    def train(self, training_df, label='next_up'):
        if training_df is None or training_df.empty:
            raise ValueError('Dados de treino inválidos')

        required = [label, 'rsi', 'macd', 'macd_signal', 'adx', 'bb_width', 'volume_ratio']
        for c in required:
            if c not in training_df.columns:
                raise ValueError(f"Coluna obrigatória faltando: {c}")

        X = training_df[['rsi', 'macd', 'macd_signal', 'adx', 'bb_width', 'volume_ratio']]
        y = training_df[label].astype(int)

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=42)

        model = RandomForestClassifier(n_estimators=125, random_state=42, n_jobs=-1)
        model.fit(X_train, y_train)

        y_pred = model.predict(X_test)
        acc = accuracy_score(y_test, y_pred)

        self.model = model
        self.save()

        return {'accuracy': acc, 'n_train': len(X_train), 'n_test': len(X_test)}

    def predict(self, df):
        if self.model is None:
            return {'signal': 'NEUTRO', 'confidence': 0.0}

        X = self._build_features(df).fillna(0)
        proba = self.model.predict_proba(X)[0]
        pos = float(proba[1] if len(proba) > 1 else proba[0])

        signal = 'BUY' if pos > 0.55 else 'SELL' if pos < 0.45 else 'NEUTRO'
        return {'signal': signal, 'confidence': float(pos)}

    def save(self):
        joblib.dump(self.model, self.model_path)

    def load(self):
        if os.path.exists(self.model_path):
            self.model = joblib.load(self.model_path)

    def add_training_row(self, row_dict):
        os.makedirs(os.path.dirname(self.dataset_path), exist_ok=True)

        df = pd.DataFrame([row_dict])
        if os.path.exists(self.dataset_path):
            df_all = pd.read_csv(self.dataset_path)
            df = pd.concat([df_all, df], ignore_index=True)

        df.to_csv(self.dataset_path, index=False)
        return len(df)
