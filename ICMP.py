import json
import os
import shutil
import sqlite3
import time
import functools

def timing_decorator(func):
    """性能计时装饰器"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        elapsed = end_time - start_time
        logger.debug(f"{func.__name__} executed in {elapsed:.3f} seconds")
        return result
    return wrapper
import uvicorn
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Optional, Dict, Any
import hashlib
import threading
import PyPDF2
import chromadb
import docx2txt
import gradio as gr
import requests
from fastapi import FastAPI
from tavily import TavilyClient
import webbrowser

# 尝试导入dotenv，如果不存在则忽略
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 配置管理
def get_config():
    """获取应用配置"""
    def get_env(key, default=""):
        return os.environ.get(key, default)

    config = {
        # API配置（无默认值，必须通过环境变量设置）
        "BAIDU_API_KEY": get_env("BAIDU_API_KEY"),
        "BAIDU_SECRET_KEY": get_env("BAIDU_SECRET_KEY"),
        "TAVILY_API_KEY": get_env("TAVILY_API_KEY"),

        # 路径配置
        "DATABASE_PATH": get_env("DATABASE_PATH", "chat_history.db"),
        "CHROMA_DB_PATH": get_env("CHROMA_DB_PATH", "chroma_db"),
        "UPLOAD_DIR": get_env("UPLOAD_DIR", "uploads"),

        # 应用配置
        "HOST": get_env("HOST", "127.0.0.1"),
        "PORT": int(get_env("PORT", "8000")),
        "DEBUG": get_env("DEBUG", "False").lower() == "true",

        # 文件上传限制（MB）
        "MAX_UPLOAD_SIZE": int(get_env("MAX_UPLOAD_SIZE", "32")),

        # 文本分割配置
        "CHUNK_SIZE": int(get_env("CHUNK_SIZE", "200")),
        "CHUNK_OVERLAP": int(get_env("CHUNK_OVERLAP", "20")),
        "MAX_BATCH_SIZE": int(get_env("MAX_BATCH_SIZE", "16")),

        # ChromaDB配置
        "COLLECTION_NAME": get_env("COLLECTION_NAME", "documents"),
    }

    # 验证必要配置
    if not config["BAIDU_API_KEY"] or not config["BAIDU_SECRET_KEY"]:
        raise ValueError("百度API密钥未配置，请设置BAIDU_API_KEY和BAIDU_SECRET_KEY环境变量")
    if not config["TAVILY_API_KEY"]:
        logging.warning("TAVILY_API_KEY未配置，网络搜索功能可能不可用")

    return config

# 加载配置
CONFIG = get_config()

# 性能优化：缓存
embedding_cache = {}
query_cache = {}
cache_lock = threading.Lock()
CACHE_TTL_SECONDS = 3600  # 1小时缓存

def print_config():
    """打印当前配置（不显示敏感信息）"""
    logger.info("=== 应用配置 ===")
    logger.info(f"数据库路径: {CONFIG['DATABASE_PATH']}")
    logger.info(f"ChromaDB路径: {CONFIG['CHROMA_DB_PATH']}")
    logger.info(f"上传目录: {CONFIG['UPLOAD_DIR']}")
    logger.info(f"主机: {CONFIG['HOST']}:{CONFIG['PORT']}")
    logger.info(f"调试模式: {CONFIG['DEBUG']}")
    logger.info(f"最大上传大小: {CONFIG['MAX_UPLOAD_SIZE']}MB")
    logger.info(f"文本块大小: {CONFIG['CHUNK_SIZE']}")
    logger.info(f"文本块重叠: {CONFIG['CHUNK_OVERLAP']}")
    logger.info(f"最大批处理大小: {CONFIG['MAX_BATCH_SIZE']}")
    logger.info(f"集合名称: {CONFIG['COLLECTION_NAME']}")
    logger.info("================")
    # 配置日志系统

def get_path(path_f):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(current_dir, path_f)

import logging
import sys

def setup_logging():
    """配置日志系统"""
    log_level = logging.DEBUG if CONFIG['DEBUG'] else logging.INFO

    # 创建日志目录
    log_dir = get_path("logs")
    os.makedirs(log_dir, exist_ok=True)

    # 配置日志格式
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'

    # 创建根日志记录器
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # 清除现有的处理器
    logger.handlers.clear()

    # 文件处理器
    file_handler = logging.FileHandler(
        filename=os.path.join(log_dir, 'app.log'),
        encoding='utf-8'
    )
    file_handler.setLevel(log_level)
    file_formatter = logging.Formatter(log_format, datefmt=date_format)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_formatter = logging.Formatter('%(levelname)s: %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    return logger

# 初始化日志
logger = setup_logging()

class ChatHisDataBase:
    def __init__(self, db_name: str = "user_data.db"):
        self.db_name = db_name
        self._init_database()
    
    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_name)
    
    def _init_database(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password TEXT NOT NULL,
                    int_value INTEGER DEFAULT 0,
                    chat_history TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 检查并添加缺失的列
            cursor.execute("PRAGMA table_info(users)")
            columns = [col[1] for col in cursor.fetchall()]

            if 'password' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN password TEXT NOT NULL DEFAULT 'default_password_hash'")
                # 更新现有行的密码为默认哈希
                default_hash = self.hash_password("default_password")
                cursor.execute("UPDATE users SET password = ?", (default_hash,))
                print("已添加password列到users表")

            if 'created_at' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN created_at TIMESTAMP")
                # 为现有行设置默认值为当前时间
                cursor.execute("UPDATE users SET created_at = datetime('now') WHERE created_at IS NULL")
                print("已添加created_at列到users表")

    def hash_password(self, password: str) -> str:
        """哈希密码"""
        return hashlib.sha256(password.encode()).hexdigest()

    def verify_password(self, password: str, hashed_password: str) -> bool:
        """验证密码"""
        return self.hash_password(password) == hashed_password

    def user_exists(self, username: str) -> bool:
        """检查用户是否存在"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM users WHERE username = ?", (username,))
            return cursor.fetchone() is not None

    def get_user_data(self, username: str) -> Optional[Dict[str, Any]]:
        """获取用户数据"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT password, int_value, chat_history FROM users WHERE username = ?",
                (username,)
            )
            result = cursor.fetchone()

            if not result:
                return None

            password, int_value, chat_history_json = result

            try:
                chat_history = json.loads(chat_history_json) if chat_history_json else {}
            except json.JSONDecodeError:
                chat_history = {}

            return {
                "password": password,
                "chat_n": int_value,
                "chat_history": chat_history
            }
    
    def update_user_data(
        self,
        username: str,
        int_value: Optional[int] = None,
        chat_history: Optional[Dict[str, Any]] = None
    ) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if self.user_exists(username):
                if int_value is not None and chat_history is not None:
                    chat_history_json = json.dumps(chat_history, ensure_ascii=False)
                    cursor.execute(
                        "UPDATE users SET int_value = ?, chat_history = ? WHERE username = ?",
                        (int_value, chat_history_json, username)
                    )
                elif int_value is not None:
                    cursor.execute(
                        "UPDATE users SET int_value = ? WHERE username = ?",
                        (int_value, username)
                    )
                elif chat_history is not None:
                    chat_history_json = json.dumps(chat_history, ensure_ascii=False)
                    cursor.execute(
                        "UPDATE users SET chat_history = ? WHERE username = ?",
                        (chat_history_json, username)
                    )
            else:
                # 为新用户插入记录，设置默认密码
                int_value = int_value if int_value is not None else 0
                chat_history = chat_history if chat_history is not None else {}
                chat_history_json = json.dumps(chat_history, ensure_ascii=False)
                default_password = self.hash_password("default_password")  # 默认密码

                cursor.execute(
                    "INSERT INTO users (username, password, int_value, chat_history) VALUES (?, ?, ?, ?)",
                    (username, default_password, int_value, chat_history_json)
                )

            conn.commit()
            return True


    def register_user(self, username: str, password: str) -> bool:
        """注册新用户"""
        if self.user_exists(username):
            return False

        hashed_password = self.hash_password(password)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, password, int_value, chat_history) VALUES (?, ?, ?, ?)",
                (username, hashed_password, 1, json.dumps({"1": {"date": str(date.today()), "his": [{"role": "assistant", "content": "你好！我是你的智能文档助手。我可以帮你：\n\n1. 📁 上传文档（PDF/TXT/DOCX）\n2. 🔍 搜索文档内容\n3. 🌐 进行网络搜索\n4. 💬 智能对话\n\n请上传文档或开始对话吧！"}]}}))
            )
            conn.commit()
        return True

    def authenticate_user(self, username: str, password: str) -> bool:
        """验证用户登录"""
        user_data = self.get_user_data(username)
        if not user_data:
            return False
        return self.verify_password(password, user_data["password"])

    def delete_user(self, username: str) -> bool:
        """删除用户"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE username = ?", (username,))
            conn.commit()
            return cursor.rowcount > 0

def get_access_token(max_retries=3):
    """获取百度文心API访问令牌，支持重试机制"""
    url = "https://aip.baidubce.com/oauth/2.0/token"
    params = {
        'grant_type': 'client_credentials',
        'client_id': CONFIG['BAIDU_API_KEY'],
        'client_secret': CONFIG['BAIDU_SECRET_KEY']
    }

    for attempt in range(max_retries):
        try:
            response = requests.post(url, params=params, timeout=10)
            response.raise_for_status()  # 检查HTTP错误
            result = response.json()

            access_token = result.get('access_token')
            if access_token:
                return str(access_token)
            else:
                error_msg = result.get('error_description', '未知错误')
                print(f"获取access_token失败 (尝试 {attempt + 1}/{max_retries}): {error_msg}")

        except requests.exceptions.Timeout:
            print(f"请求超时 (尝试 {attempt + 1}/{max_retries})")
        except requests.exceptions.RequestException as e:
            print(f"网络请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
        except json.JSONDecodeError as e:
            print(f"JSON解析失败 (尝试 {attempt + 1}/{max_retries}): {e}")

        # 如果不是最后一次尝试，等待后重试
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)  # 指数退避

    raise Exception(f"获取access_token失败，已重试{max_retries}次")


@timing_decorator
@lru_cache(maxsize=1024)
def get_embedding(texts: tuple, max_retries=3):
    """获取文本嵌入向量，支持重试机制和缓存"""
    # 生成缓存键
    cache_key = hashlib.md5(str(texts).encode()).hexdigest()

    # 检查缓存
    with cache_lock:
        if cache_key in embedding_cache:
            cached_time, embeddings = embedding_cache[cache_key]
            if time.time() - cached_time < CACHE_TTL_SECONDS:
                logger.debug(f"缓存命中: {cache_key[:8]}...")
                return embeddings

    global access_token
    texts = list(texts)
    if not access_token:
        access_token = get_access_token()

    url = f"https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/embeddings/embedding-v1?access_token={access_token}"
    payload = json.dumps({"input": texts})
    headers = {'Content-Type': 'application/json'}

    for attempt in range(max_retries):
        try:
            resp = requests.post(url, headers=headers, data=payload, timeout=30)
            resp.raise_for_status()
            response = resp.json()

            if 'error_code' in response:
                error_msg = response.get('error_msg', '未知错误')
                logger.warning(f"百度文心API错误 (尝试 {attempt + 1}/{max_retries}): {error_msg}")

                # 如果是token无效，尝试刷新token
                if response.get('error_code') in [110, 111]:  # token相关错误
                    logger.info("尝试刷新access_token...")
                    access_token = get_access_token()
                    url = f"https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/embeddings/embedding-v1?access_token={access_token}"

                # 等待后重试
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                continue

            if 'data' in response:
                embs = [e["embedding"] for e in response['data']]
                # 存入缓存
                with cache_lock:
                    embedding_cache[cache_key] = (time.time(), embs)
                logger.debug(f"获取嵌入向量成功: {len(texts)}个文本，{len(embs[0]) if embs else 0}维")
                return embs
            else:
                logger.warning(f"未知的API响应格式 (尝试 {attempt + 1}/{max_retries}): {response}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                continue

        except requests.exceptions.Timeout:
            logger.warning(f"嵌入请求超时 (尝试 {attempt + 1}/{max_retries})")
        except requests.exceptions.RequestException as e:
            logger.warning(f"嵌入请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
        except json.JSONDecodeError as e:
            logger.warning(f"嵌入响应JSON解析失败 (尝试 {attempt + 1}/{max_retries}): {e}")

        # 如果不是最后一次尝试，等待后重试
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)

    logger.error(f"获取嵌入向量失败，已重试{max_retries}次")
    return []


def chat(ms_func, max_retries=3):
    """聊天函数，支持重试机制"""
    global access_token
    if not access_token:
        access_token = get_access_token()

    url = "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions?access_token=" + access_token
    payload = json.dumps({"messages": ms_func})
    headers = {'Content-Type': 'application/json'}

    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, data=payload, timeout=30)
            response.raise_for_status()
            result = response.json()

            if 'error_code' in result:
                error_msg = result.get('error_msg', '未知错误')
                print(f"聊天API错误 (尝试 {attempt + 1}/{max_retries}): {error_msg}")

                # 如果是token无效，尝试刷新token
                if result.get('error_code') in [110, 111]:  # token相关错误
                    print("尝试刷新access_token...")
                    access_token = get_access_token()
                    url = "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions?access_token=" + access_token

                # 等待后重试
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                continue

            return result.get('result', '抱歉，我暂时无法回答这个问题。')

        except requests.exceptions.Timeout:
            print(f"聊天请求超时 (尝试 {attempt + 1}/{max_retries})")
        except requests.exceptions.RequestException as e:
            print(f"聊天请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
        except json.JSONDecodeError as e:
            print(f"聊天响应JSON解析失败 (尝试 {attempt + 1}/{max_retries}): {e}")
        except KeyError as e:
            print(f"聊天响应格式错误 (尝试 {attempt + 1}/{max_retries}): {e}，响应: {result if 'result' in locals() else '无响应'}")

        # 如果不是最后一次尝试，等待后重试
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)

    return "抱歉，服务暂时不可用，请稍后重试。"


def stream_chat(messages, max_retries=3):
    """流式聊天函数，支持重试机制"""
    global access_token
    if not access_token:
        access_token = get_access_token()

    url = f"https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions?access_token={access_token}"
    payload = {"messages": messages, "stream": True}

    for attempt in range(max_retries):
        try:
            resp = requests.post(url, json=payload, stream=True, timeout=30)
            resp.raise_for_status()

            full_response = ""
            for line in resp.iter_lines():
                if line:
                    line_str = line.decode('utf-8')
                    if line_str.startswith('data: '):
                        data_str = line_str[6:]
                        if data_str != '[DONE]':
                            try:
                                data = json.loads(data_str)
                                if 'error_code' in data:
                                    error_msg = data.get('error_msg', '未知错误')
                                    yield f"API错误: {error_msg}"
                                    break
                                if 'result' in data:
                                    chunk = data['result']
                                    full_response += chunk
                                    yield full_response
                            except json.JSONDecodeError:
                                continue
            return full_response

        except requests.exceptions.Timeout:
            error_msg = f"流式聊天请求超时 (尝试 {attempt + 1}/{max_retries})"
            print(error_msg)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            yield error_msg
            break

        except requests.exceptions.RequestException as e:
            error_msg = f"流式聊天请求失败 (尝试 {attempt + 1}/{max_retries}): {e}"
            print(error_msg)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            yield error_msg
            break

        except Exception as e:
            error_msg = f"流式聊天发生错误 (尝试 {attempt + 1}/{max_retries}): {str(e)}"
            print(error_msg)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            yield error_msg
            break

    yield "抱歉，服务暂时不可用，请稍后重试。"


def extract_text_from_pdf(pdf_path):
    try:
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            pages_text = []
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                text = page.extract_text()
                if text.strip():
                    pages_text.append(text)
            return pages_text
    except Exception as e:
        print(f"PDF文本提取失败: {e}")
        return []


def extract_text_from_txt(txt_path):
    try:
        with open(txt_path, 'r', encoding='utf-8') as file:
            text = file.read()
        return [text] if text.strip() else []
    except UnicodeDecodeError:
        try:
            with open(txt_path, 'r', encoding='gbk') as file:
                text = file.read()
            return [text] if text.strip() else []
        except Exception as e:
            print(f"TXT文本提取失败: {e}")
            return []
    except Exception as e:
        print(f"TXT文本提取失败: {e}")
        return []


def extract_text_from_docx(docx_path):
    try:
        text = docx2txt.process(docx_path)
        return [text] if text.strip() else []
    except Exception as e:
        print(f"DOCX文本提取失败: {e}")
        return []


def initialize_text_splitter(chunk_size=None, chunk_overlap=None):
    from langchain.text_splitter import RecursiveCharacterTextSplitter
    if chunk_size is None:
        chunk_size = CONFIG['CHUNK_SIZE']
    if chunk_overlap is None:
        chunk_overlap = CONFIG['CHUNK_OVERLAP']
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "！", "？", "，", "、", ""]
    )


def create_chroma_collection(collection_name=None):
    global client
    if collection_name is None:
        collection_name = CONFIG['COLLECTION_NAME']
    try:
        collection = client.get_collection(name=collection_name)
        print(f"找到现有集合: {collection_name}")
    except Exception as e:
        print(f"创建新集合: {collection_name}")
        collection = client.create_collection(
            name=collection_name,
            metadata={"description": "文档向量存储"}
        )
    return collection


def store_document_in_chromadb(file_path, file_name, file_type, collection_name=None, chunk_size=None, chunk_overlap=None):
    if collection_name is None:
        collection_name = CONFIG['COLLECTION_NAME']
    if chunk_size is None:
        chunk_size = CONFIG['CHUNK_SIZE']
    if chunk_overlap is None:
        chunk_overlap = CONFIG['CHUNK_OVERLAP']
    if file_type == '.pdf':
        pages_text = extract_text_from_pdf(file_path)
    elif file_type == '.txt':
        pages_text = extract_text_from_txt(file_path)
    elif file_type == '.docx':
        pages_text = extract_text_from_docx(file_path)
    else:
        return False, f"不支持的文件类型: {file_type}"
    
    if not pages_text:
        return False, f"未从文件中提取到文本内容"
    
    text_splitter = initialize_text_splitter(chunk_size, chunk_overlap)
    collection = create_chroma_collection(collection_name)
    
    documents = []
    metadatas = []
    ids = []
    
    for page_num, page_text in enumerate(pages_text):
        chunks = text_splitter.split_text(page_text)
        for chunk_num, chunk in enumerate(chunks):
            if chunk.strip():
                documents.append(chunk)
                metadatas.append({
                    "source": file_name,
                    "file_type": file_type,
                    "page": page_num + 1,
                    "chunk": chunk_num + 1
                })
                ids.append(f"doc_{file_name}_{page_num+1}_{chunk_num+1}")
    
    if not documents:
        return False, "没有有效的文档块可处理"
    
    print(f"准备处理 {len(documents)} 个文档块，文件: {file_name}")
    
    max_batch_size = CONFIG['MAX_BATCH_SIZE']
    all_embeddings = []
    
    for i in range(0, len(documents), max_batch_size):
        batch_end = min(i + max_batch_size, len(documents))
        batch_docs = documents[i:batch_end]
        batch_metadatas = metadatas[i:batch_end]
        batch_ids = ids[i:batch_end]
        
        print(f"处理第 {i//max_batch_size + 1} 批，共 {len(batch_docs)} 个文档块")
        
        embeddings = get_embedding(tuple(batch_docs))
        
        if not embeddings:
            print(f"第 {i//max_batch_size + 1} 批获取嵌入向量失败，跳过该批次")
            continue
        
        all_embeddings.extend(embeddings)
        
        collection.add(
            documents=batch_docs,
            metadatas=batch_metadatas,
            embeddings=embeddings,
            ids=batch_ids
        )
        
        print(f"第 {i//max_batch_size + 1} 批处理完成")
    
    if not all_embeddings:
        return False, "没有成功获取任何嵌入向量"
    
    return True, f"成功将文档存储到向量数据库，共处理 {len(all_embeddings)} 个文档块"


def process_uploaded_file(file):
    if file is None:
        return
    
    try:
        file_path = file.name
        file_name = os.path.basename(file_path)
        file_ext = os.path.splitext(file_name)[1].lower()
        
        allowed_extensions = ['.pdf', '.txt', '.docx']
        if file_ext not in allowed_extensions:
            print(f"不支持的文件类型: {file_ext}，请上传 PDF、TXT 或 DOCX 文件")
            return
        
        file_size = os.path.getsize(file_path) / (1024 * 1024)
        if file_size > CONFIG['MAX_UPLOAD_SIZE']:
            print(f"文件太大 ({file_size:.2f}MB)，请上传不超过{CONFIG['MAX_UPLOAD_SIZE']}MB的文件")
            return
        
        upload_dir = get_path(CONFIG['UPLOAD_DIR'])
        os.makedirs(upload_dir, exist_ok=True)
        
        save_path = os.path.join(upload_dir, file_name)
        counter = 1
        while os.path.exists(save_path):
            name, ext = os.path.splitext(file_name)
            save_path = os.path.join(upload_dir, f"{name}_{counter}{ext}")
            counter += 1
        
        shutil.copy2(file_path, save_path)
        
        print(f"正在处理文件: {file_name}...")
        
        success, message = store_document_in_chromadb(
            file_path=save_path,
            file_name=os.path.basename(save_path),
            file_type=file_ext
        )
        
        if success:
            print(f"✅ 文件处理成功: {os.path.basename(save_path)}\n{message}")
        else:
            print(f"❌ 文件处理失败: {os.path.basename(save_path)}\n{message}")
        
    except Exception as e:
        error_msg = f"文件处理出错: {str(e)}"
        print(error_msg)


def query_chromadb(query_text, collection_name=None, n_results=5):
    if collection_name is None:
        collection_name = CONFIG['COLLECTION_NAME']
    global client
    try:
        collection = client.get_collection(name=collection_name)
        query_embedding = get_embedding((query_text,))[0]
        
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"]
        )
        
        if not results["documents"][0]:
            return None
        
        ans = {
            "documents": results["documents"][0],
            "metadatas": results["metadatas"][0],
            "distances": results["distances"][0],
            "ids": results["ids"][0]
        }
        print(f"查询到 {len(ans['documents'])} 个相关文档块")
        return ans
    except Exception as e:
        print(f"查询失败: {e}")
        return None


def res_str(query_result):
    if not query_result:
        return "数据库未找到相关结果"
    
    result_string = "从上传的文档中检索到以下相关信息：\n" + "="*50 + "\n"
    
    for i, (doc, metadata, distance) in enumerate(zip(
        query_result["documents"], 
        query_result["metadatas"], 
        query_result["distances"]
    )):
        result_string += f"\n【相关段落 {i+1}】\n"
        result_string += f"来源文件: {metadata['source']}\n"
        if metadata.get('page'):
            result_string += f"页码/位置: {metadata['page']}\n"
        result_string += f"相关度: {1 - distance/2:.2%}\n"
        result_string += f"内容: {doc[:300]}...\n"
        result_string += "-" * 50 + "\n"
    
    return result_string


def chat_search(query):
    global tavily_client
    response = tavily_client.search(query)
    text = str(response)
    return f"从网络搜索中检索到了以下内容：\n{text}\n\n用户问题：{query}"


def chat_chromaDB(query):
    result = query_chromadb(query)
    if result:
        return res_str(result)
    else:
        return "数据库中未找到相关文档信息，请先上传相关文档或尝试网络搜索。"


@timing_decorator
def detect_intent(query):
    query_lower = query.lower().strip()

    # 本地规则检测
    doc_keywords = ['文档', '文件', '上传', 'pdf', 'txt', 'docx', '内容', '资料', '材料', '文档中', '文件里']
    search_keywords = ['网络', '上网', '百度', '谷歌']

    has_doc_keyword = any(keyword in query_lower for keyword in doc_keywords)
    has_search_keyword = any(keyword in query_lower for keyword in search_keywords)

    # 规则1：包含文档关键词 -> 文档查询
    if has_doc_keyword and not has_search_keyword:
        logger.debug(f"本地意图检测: 文档相关查询 - {query}")
        db_result = chat_chromaDB(query)
        if "未找到相关文档" in db_result:
            return f"{db_result}\n\n请尝试网络搜索或上传相关文档。"
        return db_result

    # 规则2：包含搜索关键词 -> 网络搜索
    if has_search_keyword:
        logger.debug(f"本地意图检测: 网络搜索查询 - {query}")
        return chat_search(query)

    # 规则3：无法确定，使用API检测
    logger.debug(f"本地意图检测无法确定，使用API检测 - {query}")
    ms_intent = [{"role": "user", "content": """你是一个智能文档管理助手。你的任务是分析用户的输入，并判断其最可能的意图。

可选的意图类别包括：
- 1: 想查询私有文档内相关的内容。
- 2: 想进行网络检索查询。
- 0: 无法归为以上任何一类的其他意图。

输出要求：
请严格按照以下格式输出，不要添加任何其他解释：
意图类别数字
用户输入：
""" + query}]
    intent_num = chat(ms_intent)
    logger.debug(f"API意图识别结果: {intent_num}")
    intent_num = intent_num.strip()

    if '1' in intent_num:
        db_result = chat_chromaDB(query)
        if "未找到相关文档" in db_result:
            return f"{db_result}\n\n请尝试网络搜索或上传相关文档。"
        return db_result
    elif '2' in intent_num:
        return chat_search(query)
    else:
        return query


def ms_to_his(messages):
    """将消息列表转换为Gradio Chatbot的messages格式"""
    gradio_messages = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role and content:
            gradio_messages.append({"role": role, "content": content})

    # 如果没有消息，添加欢迎消息
    if not gradio_messages:
        gradio_messages.append({"role": "assistant", "content": "你好！我是你的智能文档助手。我可以帮你：\n\n1. 📁 上传文档（PDF/TXT/DOCX）\n2. 🔍 搜索文档内容\n3. 🌐 进行网络搜索\n4. 💬 智能对话\n\n请上传文档或开始对话吧！"})

    return gradio_messages


def generate_conversation_title(user_message: str) -> str:
    """使用大模型生成对话标题"""
    try:
        # 限制输入长度
        if len(user_message) > 200:
            user_message = user_message[:200] + "..."

        prompt = f"""请根据以下用户的第一条消息生成一个简短、有意义的对话标题（最多10个汉字）：
用户消息：{user_message}

标题要求：
1. 简洁明了，反映对话主题
2. 最多10个汉字
3. 不要使用引号、冒号等标点
4. 直接返回标题，不要解释

对话标题："""

        # 使用聊天API生成标题
        response = chat([{"role": "user", "content": prompt}])

        # 清理响应
        title = response.strip()
        # 移除可能的标点
        title = title.replace('"', '').replace("'", "").replace(":", "").replace("：", "")
        # 截断到20个字符（防止过长）
        if len(title) > 20:
            title = title[:20] + "..."

        return title if title else "新对话"
    except Exception as e:
        logger.error(f"生成对话标题失败: {e}")
        # 回退方案：使用用户消息的前10个字符
        if user_message:
            if len(user_message) > 10:
                return user_message[:10] + "..."
            return user_message
        return "新对话"


def visible_change():
    global chat_ids, chat_his
    # 初始化 chat_ids 矩阵，4个分组，每组20个槽位
    chat_ids = [[-1] * 20 for _ in range(4)]
    # 将聊天记录按日期分组分配到槽位
    for key, value in chat_his.items():
        days_diff = (date.today() - date.fromisoformat(value.get("date"))).days
        if days_diff > 7:
            group = 3
        elif days_diff > 1:
            group = 2
        elif days_diff == 1:
            group = 1
        else:  # days_diff == 0
            group = 0
        # 找到该分组第一个空槽位
        for i in range(20):
            if chat_ids[group][i] == -1:
                chat_ids[group][i] = int(key)
                break
    # vislist 的顺序：对于每个分组，先 Markdown 标题，再 20 个按钮
    # 所以更新列表必须按照相同的顺序构建
    updates = []
    for group in range(4):
        # 先处理该分组的 Markdown 标题（是否可见）
        has_visible_button = any(chat_ids[group][i] != -1 for i in range(20))
        updates.append(gr.update(visible=has_visible_button))
        # 再处理该分组的 20 个按钮
        for i in range(20):
            chat_id = chat_ids[group][i]
            if chat_id == -1:
                updates.append(gr.update(visible=False))
            else:
                chat_data = chat_his.get(str(chat_id), {})
                messages = chat_data.get("his", [])
                title = chat_data.get("title")
                if not title:
                    # 生成标题
                    for msg in messages:
                        if msg.get("role") == "user" and msg.get("content"):
                            content = msg["content"]
                            if len(content) > 20:
                                title = f"💬 {content[:20]}..."
                            else:
                                title = f"💬 {content}"
                            break
                    else:
                        for msg in messages:
                            if msg.get("role") == "assistant" and msg.get("content"):
                                content = msg["content"]
                                if len(content) > 20:
                                    title = f"🤖 {content[:20]}..."
                                else:
                                    title = f"🤖 {content}"
                                break
                        else:
                            title = f"会话 {chat_id}"
                # 确保标题不为空，且适当截断（按钮文本不宜过长）
                if not title:
                    title = f"会话 {chat_id}"
                # 限制标题长度，避免按钮显示异常
                if len(title) > 30:
                    title = title[:27] + "..."
                updates.append(gr.update(visible=True, value=title))
    return tuple(updates)


def register_user(username, password, confirm_password):
    """用户注册"""
    if not username or not password:
        return "请输入用户名和密码", "", "", ""

    if password != confirm_password:
        return "两次输入的密码不一致", "", "", ""

    if len(password) < 6:
        return "密码至少需要6位", "", "", ""

    if db.user_exists(username):
        return "用户名已存在，请选择其他用户名", "", "", ""

    if db.register_user(username, password):
        return "注册成功！请使用新账户登录", "", "", ""
    else:
        return "注册失败，请稍后重试", "", "", ""




def chat_response_stream(message, chat_history):
    if not message.strip():
        yield chat_history
        return

    # 添加用户消息到历史
    chat_history.append({"role": "user", "content": message})
    ms.append({"role": "user", "content": message})
    logger.debug(f"用户消息: {message}")

    # 构建API消息
    messages_for_api = []
    for msg in chat_history[:-1]:  # 排除最后一条（当前用户消息）
        messages_for_api.append({"role": msg["role"], "content": msg["content"]})

    # 获取上下文
    context = detect_intent(message)

    # 准备最终的消息
    final_message = f"基于以下信息回答问题：\n{context}\n\n用户问题：{message}"
    messages_for_api.append({"role": "user", "content": final_message})

    # 流式响应
    full_response = ""
    for chunk in stream_chat(messages_for_api):
        if isinstance(chunk, str):
            full_response = chunk
        else:
            full_response += chunk if isinstance(chunk, str) else ""

        # 更新聊天历史显示
        current_history = chat_history.copy()
        if len(current_history) > 0 and current_history[-1]["role"] == "user":
            # 添加助手响应
            current_history.append({"role": "assistant", "content": full_response})
        elif len(current_history) > 0 and current_history[-1]["role"] == "assistant":
            # 更新助手响应
            current_history[-1]["content"] = full_response

        yield current_history

    # 保存到历史记录
    ms.append({"role": "assistant", "content": full_response})
    # 如果是第一次用户消息且没有标题，生成标题
    if "title" not in chat_his[str(chat_id)]:
        # 查找第一条用户消息
        first_user_message = None
        for msg in ms:
            if msg.get("role") == "user" and msg.get("content"):
                first_user_message = msg["content"]
                break
        if first_user_message:
            # 生成标题
            title = generate_conversation_title(first_user_message)
            chat_his[str(chat_id)]["title"] = title
    chat_his[str(chat_id)]["his"] = ms
    chat_his[str(chat_id)]["date"] = str(date.today())
    db.update_user_data(user_id, chat_n, chat_his)
    logger.debug(f"助手响应: {full_response[:50]}...")



simple_css = """
/* ========== 全局 ========== */
.gradio-container {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    min-height: 100vh;
    padding: 20px;
    margin: 0;
}

/* ========== 登录页 ========== */
#login-container {
    background: white;
    border-radius: 20px;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.15);
    margin: 0 auto;
    max-width: 480px;
    padding: 50px 40px;
    text-align: center;
    animation: fadeIn 0.6s ease-out;
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
}

#title {
    color: #2d3436;
    font-size: 32px;
    font-weight: 700;
    margin-bottom: 12px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

#subtitle {
    color: #636e72;
    font-size: 16px;
    margin-bottom: 40px;
}

/* ========== Header ========== */
.header {
    background: white;
    border-radius: 0 0 20px 20px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
    padding: 20px 40px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.welcome-container {
    display: flex;
    align-items: center;
    gap: 15px;
}

.welcome {
    font-size: 20px;
    font-weight: 600;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

.user-avatar {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-weight: bold;
}

.exit-button {
    background: linear-gradient(135deg, #ff6b6b 0%, #ee5a52 100%);
    border: none;
    border-radius: 12px;
    color: white;
    padding: 12px 24px;
    font-weight: 600;
    cursor: pointer;
}

/* ========== 左侧栏 ========== */
.left {
    background: white;
    border-radius: 20px;
    padding: 25px;
    height: calc(100vh - 140px);
    overflow-y: auto;
}

.chat-history-container {
    overflow-y: auto;
}

.right {
    background: white;
    border-radius: 20px;
    padding: 30px;
    height: calc(100vh - 140px);
    position: relative; 
     overflow: visible;  
    box-sizing: border-box;
}


.chat-header {
    position: absolute;
    top: 30px;
    left: 30px;
    right: 30px;
    height: 80px;
    z-index: 10;
}


.chatbot-container {
    position: absolute;
    top: 130px;          
    bottom: 160px;       
    width: calc(100% - 60px); 
    left: 30px;
    right: 30px;
    overflow-y: auto;
    border-radius: 16px;
    background: #f8f9fa;
    padding: 25px;
    border: 2px solid #f1f2f6;
    box-sizing: border-box;
}


.input-area {
    position: absolute;
    bottom: 30px;
    left: 30px;
    right: 30px;
    width: calc(100% - 60px);
    height: auto;           
    min-height: 70px;       
    max-height: 140px;
    display: flex !important;
    align-items: center;
    gap: 12px;
    background: white;
    z-index: 10;
    padding: 10px 0;       
    overflow: visible;  
}

.upload-button,
.send-button {
    height: 54px !important;
    flex-shrink: 0;
    min-width: 120px;
}

.chat-text {
    flex: 1;
    min-height: 54px !important;
    max-height: 120px !important;
    resize: none;
    padding: 14px !important;
}

/* ========== 气泡样式 ========== */
.gr-chatbot {
    height: 100%;
}

.gr-chatbot .user,
.gr-chatbot .assistant {
    max-width: 85%;
    padding: 16px 20px;
    border-radius: 16px;
    line-height: 1.6;
    font-size: 15px;
}

.gr-chatbot .user {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    margin-left: auto;
}

.gr-chatbot .assistant {
    background: white;
    border: 1px solid #eee;
    margin-right: auto;
}

/* ========== 响应式 ========== */
@media (max-width: 768px) {
    .right {
        height: auto;
        min-height: 500px;
        position: static;
        padding-bottom: 100px;
    }
    
    .chat-header,
    .chatbot-container,
    .input-area {
        position: static;
        width: 100%;
        height: auto;
    }
    
    .chatbot-container {
        margin: 20px 0;
        min-height: 300px;
    }
    
    .input-area {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        padding: 10px 20px;
        box-shadow: 0 -2px 10px rgba(0,0,0,0.1);
    }
}
"""

def create_gradio_interface():
    global ms, chat_his

    with gr.Blocks(css=simple_css, theme=gr.themes.Soft()) as demo:
        # 登录界面
        with gr.Column(elem_id="login-container", visible=True) as l:
            gr.HTML("""
                <div style="text-align: center; margin-bottom: 30px;">
                    <div style="font-size: 48px; margin-bottom: 20px;">📚</div>
                    <h1 id='title'>智能文档管理平台</h1>
                    <p id='subtitle'>上传、搜索、对话 - 一站式文档智能助手</p>
                </div>
            """)

            with gr.Tabs() as auth_tabs:
                with gr.TabItem("登录", id="login"):
                    with gr.Column(elem_classes="input-field"):
                        login_username = gr.Textbox(
                            label="👤 用户名",
                            placeholder="请输入您的用户名",
                            max_lines=1,
                            container=False
                        )
                        login_password = gr.Textbox(
                            label="🔒 密码",
                            placeholder="请输入密码",
                            type="password",
                            max_lines=1,
                            container=False
                        )

                    login_status = gr.HTML("", elem_classes="status-message")

                    with gr.Row():
                        login_btn = gr.Button("🚀 登录", elem_classes="login-btn", scale=1)
                        switch_to_register_btn = gr.Button("📝 注册新账户", variant="secondary", scale=1)

                with gr.TabItem("注册", id="register"):
                    with gr.Column(elem_classes="input-field"):
                        register_username = gr.Textbox(
                            label="👤 用户名",
                            placeholder="请输入用户名（至少3位）",
                            max_lines=1,
                            container=False
                        )
                        register_password = gr.Textbox(
                            label="🔒 密码",
                            placeholder="请输入密码（至少6位）",
                            type="password",
                            max_lines=1,
                            container=False
                        )
                        confirm_password = gr.Textbox(
                            label="✅ 确认密码",
                            placeholder="请再次输入密码",
                            type="password",
                            max_lines=1,
                            container=False
                        )

                    register_status = gr.HTML("", elem_classes="status-message")

                    with gr.Row():
                        register_btn = gr.Button("📝 注册", elem_classes="register-btn", scale=1)
                        switch_to_login_btn = gr.Button("🔙 返回登录", variant="secondary", scale=1)

            gr.HTML("""
                <div style="margin-top: 40px; color: #636e72; font-size: 14px; text-align: center;">
                    <p>💡 提示：首次使用请先注册账户</p>
                    <p>📁 支持上传 PDF、TXT、DOCX 格式文档</p>
                    <p>🔍 支持文档内容搜索和网络搜索</p>
                </div>
            """)

        # 主界面头部
        with gr.Row(elem_classes="header", visible=False) as c_1:
            with gr.Column(scale=1, min_width=200):
                with gr.Row(elem_classes="welcome-container"):
                    gr.HTML("""<div class="user-avatar">👤</div>""")
                    welcome = gr.Markdown(f"<div class='welcome'>欢迎回来，{user_id}</div>")
            with gr.Column(scale=1, min_width=100):
                exit_btn = gr.Button("🚪 退出", elem_classes="exit-button")
            with gr.Column(scale=8):
                gr.Markdown("")

        # 主界面内容
        with gr.Row(visible=False) as c_2:
            # 左侧边栏
            with gr.Column(scale=1, elem_classes="left"):
                new_chat = gr.Button("💬 新建对话", elem_classes="new_chat-button")

                with gr.Column(elem_classes="chat-history-container"):
                    button_data = []
                    data_list = ["📅 今天", "📅 昨天", "📅 前7天", "📅 更早"]
                    vislist = []

                    for i, i1 in enumerate(data_list):
                        mk_temp = gr.Markdown(f"<div class='section-title'>{i1}</div>", visible=False)
                        vislist.append(mk_temp)

                        for i2 in range(20):
                            btn = gr.Button(
                                value="",
                                size="md",
                                visible=False,
                                variant="secondary",
                                elem_classes="c-btn"
                            )
                            vislist.append(btn)
                            button_data.append({
                                "btn": btn,
                                "day": i,
                                "chat": i2
                            })

            # 右侧聊天区域
            with gr.Column(scale=5, elem_classes="right"):
                with gr.Column(elem_classes="chat-header"):
                    gr.HTML("""
                        <h2>智能文档助手</h2>
                        <p>上传文档后，即可进行智能问答和内容搜索</p>
                    """)

                chatbot = gr.Chatbot(
                    value=[{"role": "assistant", "content": "你好！我是你的智能文档助手。我可以帮你：\n\n1. 📁 上传文档（PDF/TXT/DOCX）\n2. 🔍 搜索文档内容\n3. 🌐 进行网络搜索\n4. 💬 智能对话\n\n请上传文档或开始对话吧！"}],
                    type="messages",
                    elem_classes="chatbot-container"
                )

                with gr.Row(elem_classes="input-area"):
                    upload_btn = gr.UploadButton(
                        scale=1,
                        label="📁 上传文档",
                        elem_classes="upload-button",
                        file_types=[".pdf", ".txt", ".docx"],
                        file_count="single"
                    )
                    msg_input = gr.Textbox(
                        lines=2,
                        scale=20,
                        elem_classes="chat-text",
                        placeholder=f"💬 输入您的问题...（支持文档搜索、网络搜索和智能对话）\n📝 提示：上传的文档不超过{CONFIG['MAX_UPLOAD_SIZE']}MB，支持格式：PDF、TXT、DOCX",
                        show_label=False,
                        interactive=True,
                        max_lines=4
                    )
                    msg_submit_btn = gr.Button(scale=1, value="📤 发送", elem_classes="send-button")
        
        for data in button_data:
            btn = data["btn"]
            day_temp = data["day"]
            chat_temp=data["chat"]
            def create_handler(d_idx=day_temp, c_idx=chat_temp):
                def handler():
                    global chat_id, ms
                    chat_id = chat_ids[d_idx][c_idx]
                    if chat_id == -1:
                        # 不应该发生，因为按钮是隐藏的，但安全起见返回空列表
                        return []
                    # 确保聊天记录存在
                    if str(chat_id) not in chat_his:
                        # 如果不存在，创建一个新的聊天记录
                        chat_his[str(chat_id)] = {
                            "date": str(date.today()),
                            "title": "新对话",
                            "his": [{"role": "assistant", "content": "你好！我是你的智能文档助手。我可以帮你：\n\n1. 📁 上传文档（PDF/TXT/DOCX）\n2. 🔍 搜索文档内容\n3. 🌐 进行网络搜索\n4. 💬 智能对话\n\n请上传文档或开始对话吧！"}]
                        }
                    ms = chat_his[str(chat_id)]["his"]
                    return ms_to_his(ms)
                return handler
            btn.click(fn=create_handler(), outputs=chatbot)
        
        def submit_message(message, chat_history):
            for updated_history in chat_response_stream(message, chat_history):
                yield updated_history
            
       
        upload_btn.upload(
            fn=process_uploaded_file,
            inputs=upload_btn
        )
        msg_submit_btn.click(
            fn=submit_message,
            inputs=[msg_input, chatbot],
            outputs=chatbot
        ).then(
            lambda: "",
            outputs=msg_input
        ).then(
            fn=visible_change,
            inputs=None,
            outputs=vislist
        )
        msg_input.submit(
            fn=submit_message,
            inputs=[msg_input, chatbot],
            outputs=chatbot
        ).then(
            lambda: "",
            outputs=msg_input
        ).then(
            fn=visible_change,
            inputs=None,
            outputs=vislist
        )
        exit_btn.click(
        fn=None,
        inputs=None,
        outputs=None,
        js="() => { location.reload(); }"
    )
        def login_in(username, password):
            if not username or not password:
                return login_fail("请输入用户名和密码")

            if not db.user_exists(username):
                return login_fail("用户不存在，请先注册")

            if not db.authenticate_user(username, password):
                return login_fail("密码错误，请重试")

            # ===== 正常登录 =====
            user_data = db.get_user_data(username)

            global chat_n, chat_his, user_id, chat_id, ms
            chat_n = user_data.get("chat_n", 0)
            chat_his = user_data.get("chat_history", {})

            user_id = username

            # ✅ 防止 chat_id 不存在
            if str(chat_n) not in chat_his:
                chat_his[str(chat_n)] = {
                    "date": str(date.today()),
                    "title": "新对话",
                    "his": [
                        {"role": "assistant", "content": "你好！我是你的智能文档助手..."}
                    ]
                }
                db.update_user_data(user_id, chat_n, chat_his)

            chat_id = chat_n
            ms = chat_his[str(chat_id)]["his"]

            # ✅ 显式构造返回值（长度可控）
            updates = [
                gr.update(visible=False),  # l
                gr.update(visible=True),   # c_1
                gr.update(visible=True),   # c_2
            ]

            # ✅ vislist 一一对应
            vis_updates = visible_change()
            assert len(vis_updates) == len(vislist), "vislist 长度不匹配"

            updates.extend(vis_updates)

            updates += [
                gr.update(value=f"<div class='welcome'>欢迎回来，{user_id}</div>"),
                ms_to_his(ms),
                "",
                "",
                ""
            ]

            return tuple(updates)


        def login_fail(msg):
            empty_updates = [gr.update(visible=False) for _ in range(len(vislist))]
            return (
                gr.update(visible=True),
                gr.update(visible=False),
                gr.update(visible=False),
                *empty_updates,
                gr.update(visible=False),
                gr.update(value=[]),
                msg,
                gr.update(),
                gr.update()
            )
        # 标签页切换功能
        def switch_to_register():
            return gr.update(selected="register")

        def switch_to_login():
            return gr.update(selected="login")

        # 绑定标签页切换事件
        switch_to_register_btn.click(
            fn=switch_to_register,
            inputs=None,
            outputs=[auth_tabs]
        )

        switch_to_login_btn.click(
            fn=switch_to_login,
            inputs=None,
            outputs=[auth_tabs]
        )

        # 注册按钮事件
        register_btn.click(
            fn=register_user,
            inputs=[register_username, register_password, confirm_password],
            outputs=[register_status, register_username, register_password, confirm_password]
        )

        # 登录按钮事件
        login_btn.click(
            fn=login_in,
            inputs=[login_username, login_password],
            outputs=[l, c_1, c_2] + vislist + [welcome, chatbot, login_status, login_username, login_password]
        ).then(
            lambda: ("", ""),
            outputs=[login_username, login_password]
        )
        def create_new_chat():
            global chat_his,chat_n,chat_id,ms
            chat_n+=1
            chat_id=chat_n
            chat_his[str(chat_n)]={
                "date": str(date.today()),
                "title": "新对话",
                "his": [{"role": "assistant", "content": "你好！我是你的智能文档助手。我可以帮你：\n\n1. 📁 上传文档（PDF/TXT/DOCX）\n2. 🔍 搜索文档内容\n3. 🌐 进行网络搜索\n4. 💬 智能对话\n\n请上传文档或开始对话吧！"}]
            }
            ms=chat_his[str(chat_n)]["his"]
            db.update_user_data(user_id,chat_n,chat_his)
            return ms_to_his(ms)
        new_chat.click(
            fn=create_new_chat,
            inputs=None,
            outputs=[chatbot]
        ).then(
            fn=visible_change,
            inputs=None,
            outputs=vislist
        )
    return demo


def initialize_test_user():
    """初始化或更新test用户数据"""
    global db  # 声明db为全局变量
    from datetime import date, timedelta

    today = date.today()

    test_conversations = {
        "1": {
            "date": str(today - timedelta(days=1)),  # 昨天
            "his": [
                {"role": "assistant", "content": "你好！我是你的智能文档助手。今天有什么可以帮助你的吗？"},
                {"role": "user", "content": "我刚上传了一个关于机器学习的PDF文档。你能总结一下主要内容吗？"},
                {"role": "assistant", "content": "当然可以！机器学习是人工智能的一个子集，专注于让计算机从数据中学习并做出预测或决策。主要类型包括监督学习、无监督学习和强化学习。"},
                {"role": "user", "content": "监督学习和无监督学习有什么区别？"},
                {"role": "assistant", "content": "监督学习使用带标签的训练数据来学习从输入到输出的映射，比如分类和回归。无监督学习在无标签数据中寻找模式，比如聚类和降维。"},
                {"role": "user", "content": "那深度学习呢？"},
                {"role": "assistant", "content": "深度学习使用多层神经网络来学习数据的层次表示。它在图像识别、自然语言处理和其他复杂任务中取得了突破性进展。"}
            ]
        },
        "2": {
            "date": str(today - timedelta(days=2)),  # 前天
            "his": [
                {"role": "assistant", "content": "你好！今天想讨论什么话题？"},
                {"role": "user", "content": "你能为我解释一下Python中的async/await吗？"},
                {"role": "assistant", "content": "Async/await是Python中用于异步编程的关键字。'async'声明一个函数为异步函数，'await'暂停执行直到异步操作完成。这允许非阻塞并发处理I/O密集型操作。"},
                {"role": "user", "content": "这和多线程有什么区别？"},
                {"role": "assistant", "content": "异步编程是单线程的，使用事件循环，适合I/O密集型任务。多线程并行运行多个线程，更适合CPU密集型任务，但有线程切换开销和线程安全问题需要考虑。"},
                {"role": "user", "content": "能给我一个简单的例子吗？"},
                {"role": "assistant", "content": "这是一个基本示例：\n```python\nimport asyncio\n\nasync def fetch_data():\n    await asyncio.sleep(1)  # 模拟I/O操作\n    return '数据'\n\nasync def main():\n    data = await fetch_data()\n    print(data)\n\nasyncio.run(main())\n```"}
            ]
        },
        "3": {
            "date": str(today - timedelta(days=3)),
            "his": [
                {"role": "assistant", "content": "下午好！今天想探索什么技术话题？"},
                {"role": "user", "content": "我正在学习Docker。你能解释一下容器和虚拟机的区别吗？"},
                {"role": "assistant", "content": "容器和虚拟机都提供虚拟化，但根本不同。虚拟机包含完整的操作系统运行在虚拟硬件上，消耗更多资源。容器共享主机操作系统内核，只包含应用和依赖，因此更轻量、更快。"},
                {"role": "user", "content": "那Kubernetes呢？"},
                {"role": "assistant", "content": "Kubernetes是一个容器编排平台，自动化容器化应用的部署、扩展和管理。它确保应用的高可用性、负载均衡和自愈能力。"},
                {"role": "user", "content": "初学者应该从哪里开始？"},
                {"role": "assistant", "content": "从Docker基础开始：1) 安装Docker，2) 学习Dockerfile语法，3) 理解镜像与容器的区别，4) 练习常用命令。然后学习Docker Compose和Kubernetes。"}
            ]
        },
        "4": {
            "date": str(today - timedelta(days=4)),
            "his": [
                {"role": "assistant", "content": "你好！准备好进行一些技术讨论了吗？"},
                {"role": "user", "content": "我正在设计一个API。应该用GraphQL还是REST？"},
                {"role": "assistant", "content": "这取决于你的需求。GraphQL适合：1) 灵活的客户端查询，2) 减少网络请求，3) 强类型系统。REST更适合：1) 简单的CRUD操作，2) 缓存很重要，3) 良好的可发现性，4) 团队熟悉度。"},
                {"role": "user", "content": "GraphQL有什么缺点？"},
                {"role": "assistant", "content": "GraphQL的挑战：1) 学习曲线较陡，2) 缓存比REST复杂，3) 潜在的N+1查询问题，4) 文件上传需要特殊处理，5) 监控和限流更复杂。"},
                {"role": "user", "content": "对于移动应用后端呢？"},
                {"role": "assistant", "content": "对于移动应用，GraphQL通常表现更好：1) 移动网络较慢，减少请求很重要，2) 不同屏幕尺寸需要不同数据，3) 类型安全减少错误。但对于简单的应用，REST也足够好。"}
            ]
        },
        "5": {
            "date": str(today),  # 今天
            "his": [
                {"role": "assistant", "content": "你好！我可以帮你处理文档查询。有什么可以协助的？"},
                {"role": "user", "content": "我正在学习微服务架构。你能给我一个概述吗？"},
                {"role": "assistant", "content": "微服务架构将大型应用拆分为小型、可独立部署的服务。每个服务处理特定的业务能力并通过API通信。优势包括独立部署、技术灵活性和更容易扩展。"},
                {"role": "user", "content": "有什么挑战？"},
                {"role": "assistant", "content": "主要挑战：1) 分布式系统复杂性，2) 服务间通信开销，3) 数据一致性管理，4) 部署和监控复杂性，5) 需要成熟的DevOps实践。"},
                {"role": "user", "content": "什么时候应该考虑微服务？"},
                {"role": "assistant", "content": "考虑微服务当：1) 单体应用难以维护，2) 团队规模扩大，3) 不同功能需要独立扩展，4) 想要不同的技术栈。但要避免过早采用——早期单体应用通常更简单。"}
            ]
        },
        "6": {
            "date": str(today - timedelta(days=1)),  # 昨天（另一个对话）
            "his": [
                {"role": "assistant", "content": "你好！今天想学点新东西吗？"},
                {"role": "user", "content": "我正在学习测试驱动开发（TDD）。有什么好的实践吗？"},
                {"role": "assistant", "content": "TDD遵循红-绿-重构：1) 先写一个失败的测试，2) 写最少的代码让测试通过，3) 重构改进设计。保持测试简单、快速运行并覆盖边界情况。测试应该记录行为，而不是实现细节。"},
                {"role": "user", "content": "TDD真的能提高代码质量吗？"},
                {"role": "assistant", "content": "是的，TDD的好处：1) 更清晰的代码设计，2) 更好的测试覆盖率，3) 更少的回归错误，4) 活的文档，5) 增加开发者信心。但要有效掌握需要练习。"},
                {"role": "user", "content": "初学者要避免哪些常见错误？"},
                {"role": "assistant", "content": "常见错误：1) 测试过于复杂，2) 跳过重构步骤，3) 测试依赖外部资源，4) 测试执行缓慢，5) 测试实现细节而非行为。从小开始，逐步养成习惯。"}
            ]
        },
        "7": {
            "date": str(today - timedelta(days=2)),  # 前天（另一个对话）
            "his": [
                {"role": "assistant", "content": "你好！今天想探索什么技术概念？"},
                {"role": "user", "content": "我在为后端开发选择Go和Rust。哪个更好？"},
                {"role": "assistant", "content": "两者都很优秀但不同。Go强调简单性和并发性——适合微服务和网络编程。Rust专注于安全性和性能——适合系统编程和性能关键型应用。"},
                {"role": "user", "content": "学习曲线如何？"},
                {"role": "assistant", "content": "Go学习曲线平缓，语法简洁。Rust由于所有权和生命周期的概念，学习曲线较陡，但掌握后能写出更安全的代码。Go更容易上手；Rust需要更多前期投入。"},
                {"role": "user", "content": "对于Web后端有什么推荐？"},
                {"role": "assistant", "content": "对于大多数Web后端，Go很优秀：1) 强大的标准库，2) 简单的并发模型，3) 快速编译，4) 易于部署。Rust更适合性能关键或安全关键的后端服务。"}
            ]
        },
        "8": {
            "date": str(today - timedelta(days=3)),
            "his": [
                {"role": "assistant", "content": "欢迎！今天有什么技术问题想讨论？"},
                {"role": "user", "content": "你能解释一下RESTful API设计的最佳实践吗？"},
                {"role": "assistant", "content": "RESTful API最佳实践：1) 使用正确的HTTP方法（GET、POST、PUT、DELETE），2) 对资源使用复数名词（/users），3) 返回适当的HTTP状态码，4) 对API进行版本控制，5) 提供清晰的错误信息，6) 使用一致的命名约定。"},
                {"role": "user", "content": "能举个资源路径设计的例子吗？"},
                {"role": "assistant", "content": "用户管理API示例：\n- GET /users - 列出用户\n- POST /users - 创建用户\n- GET /users/{id} - 获取用户\n- PUT /users/{id} - 更新用户\n- DELETE /users/{id} - 删除用户\n- GET /users/{id}/orders - 获取用户的订单"},
                {"role": "user", "content": "状态码呢？"},
                {"role": "assistant", "content": "常用状态码：200 OK、201 Created、204 No Content、400 Bad Request、401 Unauthorized、403 Forbidden、404 Not Found、500 Internal Server Error。一致性很重要——客户端应该能从状态码理解结果。"}
            ]
        }
    }

    # 为每个对话添加标题
    for conv_id, conv_data in test_conversations.items():
        # 查找第一条用户消息作为标题
        title = "新对话"
        for msg in conv_data["his"]:
            if msg.get("role") == "user" and msg.get("content"):
                user_msg = msg["content"]
                # 简单截取前10个字符作为标题
                if len(user_msg) > 10:
                    title = user_msg[:10] + "..."
                else:
                    title = user_msg
                break
        conv_data["title"] = title

    # 删除旧的test用户数据并重新创建，确保数据完全更新
    db.delete_user("test")

    # 使用register_user创建test用户（密码为Test@123456）
    if db.register_user("test", "123456"):
        # 更新test用户的聊天历史
        db.update_user_data("test", len(test_conversations), test_conversations)
        logger.info(f"已初始化test账户数据，包含{len(test_conversations)}个对话，日期范围: {today - timedelta(days=6)} 到 {today}")
    else:
        logger.error("无法创建test用户")

# 初始化数据库连接
db = ChatHisDataBase(get_path(CONFIG['DATABASE_PATH']))

# 全局变量初始化
user_id = "未登录用户"
chat_n = 0
chat_id = -1
chat_ids = [[-1] * 20 for _ in range(4)]
ms = [{"role": "assistant", "content": "你好！很高兴为你服务！"}]
tavily_client = None
client = None
access_token = None
chat_his = {}

# 创建必要的目录
os.makedirs(get_path(CONFIG['UPLOAD_DIR']), exist_ok=True)
os.makedirs(get_path(CONFIG['CHROMA_DB_PATH']), exist_ok=True)

# 初始化客户端
client = chromadb.PersistentClient(path=get_path(CONFIG['CHROMA_DB_PATH']))
tavily_client = TavilyClient(api_key=CONFIG['TAVILY_API_KEY'])
access_token = get_access_token()

# 应用启动时初始化test用户数据
initialize_test_user()

demo = create_gradio_interface()
app = FastAPI()

@app.get("/")
def read_root():
    return {"提示": "当前为fastAPI接口，请在网址中添加/gradio进入页面"}

app = gr.mount_gradio_app(app, demo, path="/gradio")

if __name__ == "__main__":
    # 打印配置信息
    print_config()

    webbrowser.open_new(f"http://{CONFIG['HOST']}:{CONFIG['PORT']}/gradio/")
    uvicorn.run(app, host=CONFIG['HOST'], port=CONFIG['PORT'])

    