from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
import re

db = SQLAlchemy()

# 文章与标签的多对多关联表
article_tags = db.Table('article_tags',
                        db.Column('article_id', db.Integer, db.ForeignKey('article.id')),
                        db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'))
                        )


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)

    nickname = db.Column(db.String(50))  # 昵称
    gender = db.Column(db.String(10))  # 性别
    repo_link = db.Column(db.String(200))  # 个人代码仓库链接
    bio = db.Column(db.Text)  # 个人简介
    avatar_url = db.Column(db.String(200), default='https://api.dicebear.com/9.x/croodles/svg?seed=Jessica')  # 默认头像
    last_login = db.Column(db.DateTime)

    # 关联
    articles = db.relationship('Article', backref='author', lazy=True)
    categories = db.relationship('Category', backref='owner', lazy=True)
    tags = db.relationship('Tag', backref='owner', lazy=True)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    summary = db.Column(db.Text)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    is_draft = db.Column(db.Boolean, default=False)  # 新增：是否为草稿
    update_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    cover_url = db.Column(db.String(256))

    category = db.relationship('Category', backref='posts')
    tags = db.relationship('Tag', secondary=article_tags, backref=db.backref('articles', lazy='dynamic'))
    comments = db.relationship('Comment', backref='target_article', lazy=True, cascade="all, delete-orphan")

    @property
    def word_count(self):
        """计算去除 Markdown 符号后的纯文字字数"""
        if not self.content:
            return 0

        # 1. 拷贝一份正文内容进行清理
        text = self.content

        # 2. 正则过滤逻辑
        # 去掉代码块 (```...```)
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
        # 去掉图片 (![alt](url))
        text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
        # 去掉链接，只保留链接文字 ([text](url) -> text)
        text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
        # 去掉标题符号 (# ## ###)
        text = re.sub(r'#+\s?', '', text)
        # 去掉粗体、斜体 (** * __ _)
        text = re.sub(r'(\*\*|__|[\*_])', '', text)
        # 去掉列表符号 (- * + 1. 2.)
        text = re.sub(r'^\s*[\->\*+]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
        # 去掉 HTML 标签
        text = re.sub(r'<[^>]*>', '', text)
        # 去掉多余的换行和空格
        text = "".join(text.split())

        return len(text)

    @property
    def read_time(self):
        """估算阅读时间"""
        count = self.word_count
        # 中文阅读速度通常为 300-500 字/分钟
        minutes = round(count / 400)
        return minutes if minutes > 0 else 1

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now)  # 评论时间

    # 外键关联
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey('article.id'), nullable=False)

    # 为了方便查询，给 Article 和 User 反向建立关系
    # 这样可以用 article.comments 拿到所有评论
    author = db.relationship('User', backref=db.backref('comments', lazy=True))


