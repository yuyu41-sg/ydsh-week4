# Streamlit 问答应用镜像：Python + NL2SQL 后端（连接 Hive）
FROM python:3.10-slim

WORKDIR /app
COPY app.py nl2sql.py ./
COPY data/schema.json /app/data/schema.json
COPY data/schema_prompt.txt /app/data/schema_prompt.txt

# 使用国内清华镜像源，避免 PyPI 官方源下载超时
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple streamlit pandas pymysql openai python-dotenv requests pyhive thrift thrift-sasl scikit-learn numpy

EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
