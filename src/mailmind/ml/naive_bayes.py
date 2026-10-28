"""纯 Python 多项式朴素贝叶斯（TF-IDF-ish 加权）。

不用 scikit-learn：零额外依赖、可序列化成 JSON、行为完全确定，
便于在 CI 与离线环境复现（exp.md 3.4 的 L1 基线）。
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from mailmind.ml.text import tokenize


@dataclass
class NaiveBayesModel:
    labels: list[str] = field(default_factory=list)
    vocab: dict[str, int] = field(default_factory=dict)
    # 每个 label 一份 log 似然向量，长度与 vocab 一致
    log_likelihood: dict[str, list[float]] = field(default_factory=dict)
    log_prior: dict[str, float] = field(default_factory=dict)
    alpha: float = 1.0
    trained_samples: int = 0
    version: str = "nb-v1"

    # ------------------------------------------------------------ 训练
    @classmethod
    def train(
        cls,
        samples: Iterable[tuple[str, str]],
        *,
        alpha: float = 1.0,
        min_df: int = 1,
        max_features: int = 20000,
    ) -> NaiveBayesModel:
        pairs = [(t, label) for t, label in samples if label]
        if not pairs:
            raise ValueError("训练样本为空")

        labels = sorted({label for _text, label in pairs})
        doc_freq: dict[str, int] = {}
        tokenized: list[tuple[list[str], str]] = []
        for text, label in pairs:
            toks = tokenize(text)
            tokenized.append((toks, label))
            for tok in set(toks):
                doc_freq[tok] = doc_freq.get(tok, 0) + 1

        candidates = [(tok, df) for tok, df in doc_freq.items() if df >= min_df]
        candidates.sort(key=lambda kv: (-kv[1], kv[0]))
        kept = sorted(tok for tok, _df in candidates[:max_features])
        vocab = {tok: i for i, tok in enumerate(kept)}
        size = len(vocab)

        counts = {label: [0.0] * size for label in labels}
        totals = {label: 0.0 for label in labels}
        label_docs = {label: 0 for label in labels}

        for toks, label in tokenized:
            label_docs[label] += 1
            for tok in toks:
                idx = vocab.get(tok)
                if idx is None:
                    continue
                # sublinear tf：抑制超高频词的统治力
                counts[label][idx] += 1.0
                totals[label] += 1.0

        log_prior: dict[str, float] = {}
        total_docs = sum(label_docs.values())
        for label in labels:
            log_prior[label] = math.log((label_docs[label] + alpha) / (total_docs + alpha * len(labels)))

        log_likelihood: dict[str, list[float]] = {}
        for label in labels:
            denom = totals[label] + alpha * size if size else 1.0
            log_likelihood[label] = [math.log((c + alpha) / denom) for c in counts[label]]

        return cls(
            labels=labels,
            vocab=vocab,
            log_likelihood=log_likelihood,
            log_prior=log_prior,
            alpha=alpha,
            trained_samples=len(pairs),
        )

    # ------------------------------------------------------------ 推理
    def _scores(self, tokens: list[str]) -> dict[str, float]:
        scores = {label: self.log_prior.get(label, 0.0) for label in self.labels}
        if not self.vocab:
            return scores
        length = max(len(tokens), 1)
        for tok in tokens:
            idx = self.vocab.get(tok)
            if idx is None:
                continue
            for label in self.labels:
                scores[label] += self.log_likelihood[label][idx]
        # 长度归一，避免长邮件被同一类别的累积量偏置
        return {label: score / math.sqrt(length) for label, score in scores.items()}

    def predict_proba(self, text: str) -> dict[str, float]:
        if not self.labels:
            return {}
        tokens = tokenize(text)
        scores = self._scores(tokens)
        top = max(scores.values())
        exps = {label: math.exp(score - top) for label, score in scores.items()}
        total = sum(exps.values()) or 1.0
        return {label: exps[label] / total for label in scores}

    def predict(self, text: str) -> tuple[str, float]:
        proba = self.predict_proba(text)
        if not proba:
            return "unknown", 0.0
        label = max(proba, key=proba.get)  # type: ignore[arg-type]
        return label, proba[label]

    # ------------------------------------------------------------ 解释
    def top_tokens(self, text: str, label: str, k: int = 5) -> list[tuple[str, float]]:
        """返回对该类别贡献最大的 token（用于可解释性）。"""
        if not self.vocab or label not in self.log_likelihood:
            return []
        others = [lb for lb in self.labels if lb != label]
        if not others:
            return []
        counts: dict[str, int] = {}
        for tok in tokenize(text):
            if tok in self.vocab:
                counts[tok] = counts.get(tok, 0) + 1
        scored: list[tuple[str, float]] = []
        for tok, tf in counts.items():
            idx = self.vocab[tok]
            own = self.log_likelihood[label][idx]
            best_other = max(self.log_likelihood[o][idx] for o in others)
            score = (own - best_other) * (1 + math.log(tf))
            scored.append((tok, score))
        scored.sort(key=lambda kv: -kv[1])
        return scored[:k]

    # ------------------------------------------------------------ 持久化
    def to_dict(self) -> dict:
        return {
            "labels": self.labels,
            "vocab": self.vocab,
            "log_likelihood": self.log_likelihood,
            "log_prior": self.log_prior,
            "alpha": self.alpha,
            "trained_samples": self.trained_samples,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> NaiveBayesModel:
        return cls(
            labels=list(payload["labels"]),
            vocab=dict(payload["vocab"]),
            log_likelihood={k: list(v) for k, v in payload["log_likelihood"].items()},
            log_prior=dict(payload["log_prior"]),
            alpha=float(payload.get("alpha", 1.0)),
            trained_samples=int(payload.get("trained_samples", 0)),
            version=str(payload.get("version", "nb-v1")),
        )

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> NaiveBayesModel:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
