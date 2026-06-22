# ICMP - Intelligent Chat-based Multi-document Platform

A Gradio-based document management assistant with authentication, vector search, and conversational AI capabilities.

## Features

- **User Authentication**: Secure login/registration system with SQLite database
- **Document Upload**: Support for PDF, TXT, and DOCX files
- **Vector Search**: ChromaDB integration for semantic document retrieval
- **Conversational AI**: Integration with Baidu Wenxin API for intelligent Q&A
- **Web Search**: Tavily API integration for real-time web searches
- **Chat History**: Persistent conversation storage with date-based organization
- **Streaming Responses**: Real-time chat with streaming responses
- **Modern UI**: Clean, responsive Gradio interface with CSS styling

## Prerequisites

- Python 3.8+
- Required API keys:
  - Baidu Wenxin API (for embeddings and chat)
  - Tavily API (for web search)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/a193884646/ICMP.git
cd ICMP
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
export BAIDU_API_KEY="your_baidu_api_key"
export BAIDU_SECRET_KEY="your_baidu_secret_key"
export TAVILY_API_KEY="your_tavily_api_key"
```

## Usage

Run the application:
```bash
python ICMP.py
```

The application will start a FastAPI server with Gradio interface at `http://127.0.0.1:8000/gradio`

## Configuration

The application can be configured via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `BAIDU_API_KEY` | Baidu Wenxin API key | Required |
| `BAIDU_SECRET_KEY` | Baidu Wenxin secret key | Required |
| `TAVILY_API_KEY` | Tavily API key | Required |
| `DATABASE_PATH` | SQLite database path | `chat_history.db` |
| `CHROMA_DB_PATH` | ChromaDB storage path | `chroma_db` |
| `UPLOAD_DIR` | Upload directory | `uploads` |
| `HOST` | Server host | `127.0.0.1` |
| `PORT` | Server port | `8000` |
| `DEBUG` | Debug mode | `False` |
| `MAX_UPLOAD_SIZE` | Max file upload size (MB) | `32` |
| `CHUNK_SIZE` | Text chunk size | `200` |
| `CHUNK_OVERLAP` | Text chunk overlap | `20` |
| `MAX_BATCH_SIZE` | Embedding batch size | `16` |
| `COLLECTION_NAME` | ChromaDB collection name | `documents` |

## Architecture

- **Database Layer**: SQLite for user authentication and chat history
- **Vector Store**: ChromaDB for document embeddings and semantic search
- **AI Integration**: Baidu Wenxin API for embeddings and chat completions
- **Web Interface**: Gradio for interactive UI with authentication flow
- **File Processing**: Support for PDF, TXT, and DOCX extraction

## Features in Detail

### Authentication System
- User registration and login with password hashing
- Session management with chat history persistence
- Test user with sample conversations for demonstration

### Document Processing
- Multi-format support (PDF, TXT, DOCX)
- Text extraction and chunking with configurable parameters
- Vector embeddings with caching and retry mechanisms

### Search Capabilities
- Semantic search across uploaded documents
- Web search integration for external information
- Intent detection to route queries appropriately

### Chat Interface
- Streaming responses for real-time interaction
- Conversation history with date-based organization
- Title generation for saved conversations

## License

MIT

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.