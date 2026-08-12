import datetime
import os

from flask import Flask, jsonify, request
from flask_cors import CORS
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, create_engine, text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

allowed_origins = [
    origin.strip()
    for origin in os.environ.get(
        "ALLOWED_ORIGINS",
        "https://dellimpe1-hub.github.io,http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if origin.strip()
]
CORS(app, resources={r"/api/*": {"origins": allowed_origins}})

database_url = os.environ.get("DATABASE_URL", "").strip()
if database_url.startswith("postgres://"):
    database_url = "postgresql://" + database_url.removeprefix("postgres://")

Base = declarative_base()
engine = create_engine(database_url, pool_pre_ping=True) if database_url else None
Session = sessionmaker(bind=engine) if engine else None


class Orcamento(Base):
    __tablename__ = "orcamentos"

    id = Column(Integer, primary_key=True)
    criado_em = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    nome = Column(String(120), nullable=False)
    email = Column(String(180), nullable=False)
    telefone = Column(String(40), nullable=False)
    cidade = Column(String(120), nullable=False)
    endereco = Column(String(300), nullable=False)
    latitude = Column(Float)
    longitude = Column(Float)
    assunto = Column(String(180), nullable=False)
    mensagem = Column(Text, nullable=False)
    atendido = Column(Boolean, default=False, nullable=False)
    anexos = relationship("Anexo", cascade="all, delete-orphan", back_populates="orcamento")


class Anexo(Base):
    __tablename__ = "orcamento_anexos"

    id = Column(Integer, primary_key=True)
    orcamento_id = Column(Integer, ForeignKey("orcamentos.id", ondelete="CASCADE"), nullable=False)
    nome = Column(String(255), nullable=False)
    mime = Column(String(120), nullable=False)
    tamanho = Column(Integer, nullable=False)
    dados = Column(LargeBinary, nullable=False)
    orcamento = relationship("Orcamento", back_populates="anexos")


if engine:
    Base.metadata.create_all(engine)


def parse_float(value):
    if not value:
        return None
    try:
        return float(value.replace(",", "."))
    except (AttributeError, ValueError):
        return None


@app.get("/")
def health():
    connected = False
    if engine:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            connected = True
        except Exception:
            pass
    return jsonify({"status": "ok", "servico": "DELL LIMPE API", "banco_conectado": connected})


@app.post("/api/orcamentos")
def criar_orcamento():
    if not Session:
        return jsonify({"message": "Banco de dados não configurado."}), 503

    required = ("nome", "email", "telefone", "cidade", "endereco", "assunto", "mensagem")
    values = {field: (request.form.get(field) or "").strip() for field in required}
    if any(not values[field] for field in required):
        return jsonify({"message": "Preencha todos os campos obrigatórios."}), 400

    files = [file for file in request.files.getlist("anexos") if file and file.filename]
    if len(files) > 3:
        return jsonify({"message": "Envie no máximo 3 anexos."}), 400

    allowed_mimes = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
    attachments = []
    total_size = 0
    for file in files:
        if file.mimetype not in allowed_mimes:
            return jsonify({"message": "Somente JPG, PNG, WebP e PDF são permitidos."}), 400
        content = file.read()
        total_size += len(content)
        attachments.append((file, content))
    if total_size > 8 * 1024 * 1024:
        return jsonify({"message": "Os anexos não podem ultrapassar 8 MB."}), 400

    quote = Orcamento(
        **values,
        latitude=parse_float(request.form.get("latitude")),
        longitude=parse_float(request.form.get("longitude")),
    )
    for file, content in attachments:
        quote.anexos.append(Anexo(
            nome=file.filename[:255],
            mime=file.mimetype,
            tamanho=len(content),
            dados=content,
        ))

    try:
        with Session.begin() as session:
            session.add(quote)
            session.flush()
            quote_id = quote.id
    except Exception:
        app.logger.exception("Erro ao salvar orçamento")
        return jsonify({"message": "Não foi possível salvar a solicitação."}), 500

    return jsonify({
        "success": True,
        "id": quote_id,
        "message": "Solicitação recebida! A DELL LIMPE entrará em contato.",
    }), 201


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
