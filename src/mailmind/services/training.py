"""模型训练与加载。

冷启动用 ``ml/seed.py`` 的种子语料；有真实反馈后由 ``rebuild_from_db`` 覆盖。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from mailmind.core.config import Settings
from mailmind.ml.naive_bayes import NaiveBayesModel
from mailmind.ml.seed import CATEGORY_SEED, HAM_SEED, SPAM_SEED

SPAM_FILE = "spam_model.json"
CATEGORY_FILE = "category_model.json"


def spam_samples() -> list[tuple[str, str]]:
    return [(text, "spam") for text in SPAM_SEED] + [(text, "ham") for text in HAM_SEED]


def category_samples(categories: list[str] | None = None) -> list[tuple[str, str]]:
    samples = list(CATEGORY_SEED)
    if categories:
        allowed = set(categories)
        samples = [(text, cat) for text, cat in samples if cat in allowed]
    return samples


def train_spam(extra: list[tuple[str, str]] | None = None) -> NaiveBayesModel:
    model = NaiveBayesModel.train(spam_samples() + list(extra or []), min_df=1, max_features=5000)
    model.version = "spam-nb-v1"
    return model


def train_category(
    extra: list[tuple[str, str]] | None = None, categories: list[str] | None = None
) -> NaiveBayesModel:
    model = NaiveBayesModel.train(
        category_samples(categories) + list(extra or []), min_df=1, max_features=8000
    )
    model.version = "category-nb-v1"
    return model


def model_path(settings: Settings, filename: str) -> Path:
    return Path(settings.model_dir) / filename


def load_spam_model(settings: Settings) -> NaiveBayesModel | None:
    path = model_path(settings, SPAM_FILE)
    if not path.is_file():
        return None
    try:
        return NaiveBayesModel.load(path)
    except Exception:  # noqa: BLE001 - 模型损坏时回退到启发式
        return None


def load_category_model(settings: Settings) -> NaiveBayesModel | None:
    path = model_path(settings, CATEGORY_FILE)
    if not path.is_file():
        return None
    try:
        return NaiveBayesModel.load(path)
    except Exception:  # noqa: BLE001
        return None


def save_models(settings: Settings, spam: NaiveBayesModel, category: NaiveBayesModel) -> None:
    spam.save(model_path(settings, SPAM_FILE))
    category.save(model_path(settings, CATEGORY_FILE))


def _category_model_stale(model: NaiveBayesModel, categories: list[str]) -> bool:
    """配置里新增了业务类别、但磁盘上的模型没学过 → 需要重训。"""
    expected = set(categories) - {"spam", "other"}
    return bool(expected - set(model.labels))


def ensure_models(settings: Settings, train_if_missing: bool = True) -> tuple[
    NaiveBayesModel | None, NaiveBayesModel | None
]:
    spam = load_spam_model(settings)
    category = load_category_model(settings)
    if train_if_missing and (spam is None or category is None or (category is not None and _category_model_stale(category, settings.categories))):
        if spam is None:
            spam = train_spam()
        if category is None or _category_model_stale(category, settings.categories):
            category = train_category(categories=settings.categories)
        try:
            save_models(settings, spam, category)
        except OSError:
            pass  # 只读文件系统（如容器）也能跑内存模型
    return spam, category


def rebuild_from_db(session: Session, settings: Settings) -> dict[str, int]:
    """用人工反馈重训，并写回模型文件（exp.md 4.8）。"""
    from mailmind.db.models import Feedback

    spam_extra: list[tuple[str, str]] = []
    category_extra: list[tuple[str, str]] = []
    rows = session.scalars(select(Feedback)).all()
    for row in rows:
        mail = row.mail
        if mail is None:
            continue
        text = f"{mail.subject}\n{mail.text_body}"
        label = row.label or {}
        if row.task == "spam" and label.get("label") in {"spam", "ham"}:
            # 用户反馈权重更高，重复采样
            spam_extra.extend([(text, label["label"])] * 3)
        elif row.task == "category" and label.get("category") in settings.categories:
            category_extra.extend([(text, label["category"])] * 3)

    spam = train_spam(spam_extra)
    category = train_category(category_extra, categories=settings.categories)
    save_models(settings, spam, category)
    return {"spam_samples": len(spam_samples()) + len(spam_extra),
            "category_samples": len(category_samples()) + len(category_extra)}
