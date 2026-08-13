import datetime
import base64
import hashlib
import hmac
import json
import os

from flask import Flask, Response, jsonify, request
from flask_cors import CORS
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, create_engine, text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "").strip()
SITE_PASSWORD = os.environ.get("SITE_PASSWORD", "").strip()
SITE_TOKEN_TTL = 12 * 60 * 60

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


class ServicoCard(Base):
    __tablename__ = "servico_cards"

    chave = Column(String(80), primary_key=True)
    titulo = Column(String(180), nullable=False)
    descricao = Column(Text, nullable=False)
    imagem_nome = Column(String(255))
    imagem_mime = Column(String(120))
    imagem_dados = Column(LargeBinary)
    atualizado_em = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


if engine:
    Base.metadata.create_all(engine)


def parse_float(value):
    if not value:
        return None


SERVICE_KEYS = {
    "instalacao-paineis",
    "instalacao-sistema-fotovoltaico",
    "instalacao-eletrica",
    "manutencao-preventiva",
    "limpeza-paineis",
    "manutencao-sistema-fotovoltaico",
}


def admin_authorized():
    if not ADMIN_TOKEN:
        return False
    authorization = request.headers.get("Authorization", "")
    return hmac.compare_digest(authorization, f"Bearer {ADMIN_TOKEN}")


def require_admin():
    if not admin_authorized():
        return jsonify({"message": "Acesso não autorizado."}), 401
    return None
    try:
        return float(value.replace(",", "."))
    except (AttributeError, ValueError):
        return None


def create_site_token():
    payload = {"exp": int(datetime.datetime.now(datetime.timezone.utc).timestamp()) + SITE_TOKEN_TTL}
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(SITE_PASSWORD.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def site_token_authorized():
    if not SITE_PASSWORD:
        return False
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        return False
    try:
        encoded, signature = authorization[7:].split(".", 1)
        expected = hmac.new(SITE_PASSWORD.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return False
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        return int(payload["exp"]) > int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False


@app.post("/api/acesso")
def liberar_site():
    if not SITE_PASSWORD:
        return jsonify({"message": "A senha de visitação ainda não foi configurada."}), 503
    password = str((request.get_json(silent=True) or {}).get("senha", ""))
    if not hmac.compare_digest(password, SITE_PASSWORD):
        return jsonify({"message": "Senha incorreta."}), 401
    return jsonify({"liberado": True, "token": create_site_token(), "validade_horas": 12})


@app.get("/api/acesso/verificar")
def verificar_acesso_site():
    if not site_token_authorized():
        return jsonify({"liberado": False}), 401
    return jsonify({"liberado": True})


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


@app.get("/api/servicos")
def listar_servicos():
    if not Session:
        return jsonify({"servicos": []})
    with Session() as session:
        cards = session.query(ServicoCard).all()
        return jsonify({"servicos": [{
            "chave": card.chave,
            "titulo": card.titulo,
            "descricao": card.descricao,
            "imagem_url": f"/api/servicos/{card.chave}/imagem?v={int(card.atualizado_em.timestamp())}" if card.imagem_dados else None,
        } for card in cards]})


@app.get("/api/servicos/<chave>/imagem")
def imagem_servico(chave):
    if not Session or chave not in SERVICE_KEYS:
        return jsonify({"message": "Imagem não encontrada."}), 404
    with Session() as session:
        card = session.get(ServicoCard, chave)
        if not card or not card.imagem_dados:
            return jsonify({"message": "Imagem não encontrada."}), 404
        response = Response(card.imagem_dados, mimetype=card.imagem_mime or "image/jpeg")
        response.headers["Cache-Control"] = "public, max-age=3600"
        return response


@app.get("/api/admin/verificar")
def verificar_admin():
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    return jsonify({"success": True})


@app.put("/api/admin/servicos/<chave>")
def atualizar_servico(chave):
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    if not Session or chave not in SERVICE_KEYS:
        return jsonify({"message": "Serviço inválido."}), 400

    title = (request.form.get("titulo") or "").strip()
    description = (request.form.get("descricao") or "").strip()
    if not title or not description:
        return jsonify({"message": "Informe título e descrição."}), 400

    image = request.files.get("imagem")
    image_content = None
    if image and image.filename:
        if image.mimetype not in {"image/jpeg", "image/png", "image/webp"}:
            return jsonify({"message": "Envie uma imagem JPG, PNG ou WebP."}), 400
        image_content = image.read()
        if len(image_content) > 4 * 1024 * 1024:
            return jsonify({"message": "A imagem não pode ultrapassar 4 MB."}), 400

    with Session.begin() as session:
        card = session.get(ServicoCard, chave)
        if not card:
            card = ServicoCard(chave=chave, titulo=title, descricao=description)
            session.add(card)
        card.titulo = title
        card.descricao = description
        card.atualizado_em = datetime.datetime.utcnow()
        if image_content:
            card.imagem_nome = image.filename[:255]
            card.imagem_mime = image.mimetype
            card.imagem_dados = image_content
    return jsonify({"success": True, "message": "Card atualizado."})


@app.delete("/api/admin/servicos/<chave>")
def restaurar_servico(chave):
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    if not Session or chave not in SERVICE_KEYS:
        return jsonify({"message": "Serviço inválido."}), 400
    with Session.begin() as session:
        card = session.get(ServicoCard, chave)
        if card:
            session.delete(card)
    return jsonify({"success": True, "message": "Card restaurado para o padrão."})


@app.get("/api/admin/orcamentos")
def listar_orcamentos():
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    if not Session:
        return jsonify({"message": "Banco de dados não configurado."}), 503
    with Session() as session:
        quotes = session.query(Orcamento).order_by(Orcamento.id.desc()).limit(500).all()
        return jsonify({"orcamentos": [{
            "id": quote.id,
            "criado_em": quote.criado_em.isoformat() if quote.criado_em else None,
            "nome": quote.nome,
            "email": quote.email,
            "telefone": quote.telefone,
            "cidade": quote.cidade,
            "endereco": quote.endereco,
            "latitude": quote.latitude,
            "longitude": quote.longitude,
            "assunto": quote.assunto,
            "mensagem": quote.mensagem,
            "atendido": bool(quote.atendido),
            "anexos": [{"id": item.id, "nome": item.nome, "mime": item.mime, "tamanho": item.tamanho} for item in quote.anexos],
        } for quote in quotes]})


@app.patch("/api/admin/orcamentos/<int:quote_id>")
def atualizar_orcamento(quote_id):
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    values = request.get_json(silent=True) or {}
    if "atendido" not in values:
        return jsonify({"message": "Campo inválido."}), 400
    with Session.begin() as session:
        quote = session.get(Orcamento, quote_id)
        if not quote:
            return jsonify({"message": "Solicitação não encontrada."}), 404
        quote.atendido = bool(values["atendido"])
    return jsonify({"success": True})


@app.delete("/api/admin/orcamentos/<int:quote_id>")
def excluir_orcamento(quote_id):
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    with Session.begin() as session:
        quote = session.get(Orcamento, quote_id)
        if not quote:
            return jsonify({"message": "Solicitação não encontrada."}), 404
        session.delete(quote)
    return jsonify({"success": True})


@app.get("/api/admin/anexos/<int:attachment_id>")
def baixar_anexo(attachment_id):
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    with Session() as session:
        attachment = session.get(Anexo, attachment_id)
        if not attachment:
            return jsonify({"message": "Anexo não encontrado."}), 404
        response = Response(attachment.dados, mimetype=attachment.mime)
        response.headers["Content-Disposition"] = f'attachment; filename="anexo-{attachment.id}"'
        response.headers["X-File-Name"] = attachment.nome
        return response


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
