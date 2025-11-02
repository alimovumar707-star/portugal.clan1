from fastapi import FastAPI, APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta
import bcrypt
import jwt
from emergentintegrations.llm.chat import LlmChat, UserMessage

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# JWT Config
JWT_SECRET = os.environ['JWT_SECRET_KEY']
JWT_ALGORITHM = "HS256"

# Admin Credentials
ADMIN_USERNAME = os.environ['ADMIN_USERNAME']
ADMIN_PASSWORD = os.environ['ADMIN_PASSWORD']

# Security
security = HTTPBearer()

app = FastAPI()
api_router = APIRouter(prefix="/api")

# ============ MODELS ============

class Leader(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    title: str
    description: str
    image_url: str
    order: int

class WarStatistic(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    opponent: str
    wins: int
    losses: int
    order: int

class WarStatisticCreate(BaseModel):
    opponent: str
    wins: int = 0
    losses: int = 0
    order: int = 0

class WarStatisticUpdate(BaseModel):
    opponent: Optional[str] = None
    wins: Optional[int] = None
    losses: Optional[int] = None
    order: Optional[int] = None

class GalleryImage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    image_url: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class GalleryImageCreate(BaseModel):
    image_url: str

class Testimonial(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    author_name: Optional[str] = "Анонимный воин"
    content: str
    approved: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class TestimonialCreate(BaseModel):
    author_name: Optional[str] = "Анонимный воин"
    content: str

class AdminLogin(BaseModel):
    username: str
    password: str

class AdminToken(BaseModel):
    access_token: str
    token_type: str = "bearer"

class ChatMessage(BaseModel):
    message: str
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

class ChatResponse(BaseModel):
    response: str
    session_id: str

# ============ AUTH ============

def create_access_token(data: dict, expires_delta: timedelta = timedelta(hours=24)):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

# ============ ROUTES ============

# Auth
@api_router.post("/auth/login", response_model=AdminToken)
async def admin_login(login_data: AdminLogin):
    # Check admin credentials from environment variables
    if login_data.username == ADMIN_USERNAME and login_data.password == ADMIN_PASSWORD:
        access_token = create_access_token(data={"sub": login_data.username, "role": "admin"})
        return AdminToken(access_token=access_token)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

# Leaders
@api_router.get("/leaders", response_model=List[Leader])
async def get_leaders():
    leaders = await db.leaders.find({}, {"_id": 0}).sort("order", 1).to_list(100)
    return leaders

# War Statistics
@api_router.get("/wars", response_model=List[WarStatistic])
async def get_wars():
    wars = await db.wars.find({}, {"_id": 0}).sort("order", 1).to_list(100)
    return wars

@api_router.post("/wars", response_model=WarStatistic)
async def create_war(war_data: WarStatisticCreate, token: dict = Depends(verify_token)):
    war_obj = WarStatistic(**war_data.model_dump())
    doc = war_obj.model_dump()
    await db.wars.insert_one(doc)
    return war_obj

@api_router.put("/wars/{war_id}", response_model=WarStatistic)
async def update_war(war_id: str, war_data: WarStatisticUpdate, token: dict = Depends(verify_token)):
    existing = await db.wars.find_one({"id": war_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="War not found")
    
    update_data = {k: v for k, v in war_data.model_dump().items() if v is not None}
    if update_data:
        await db.wars.update_one({"id": war_id}, {"$set": update_data})
    
    updated = await db.wars.find_one({"id": war_id}, {"_id": 0})
    return WarStatistic(**updated)

@api_router.delete("/wars/{war_id}")
async def delete_war(war_id: str, token: dict = Depends(verify_token)):
    result = await db.wars.delete_one({"id": war_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="War not found")
    return {"message": "War deleted successfully"}

# Gallery
@api_router.get("/gallery", response_model=List[GalleryImage])
async def get_gallery():
    images = await db.gallery.find({}, {"_id": 0}).sort("created_at", -1).to_list(100)
    for img in images:
        if isinstance(img.get('created_at'), str):
            img['created_at'] = datetime.fromisoformat(img['created_at'])
    return images

@api_router.post("/gallery", response_model=GalleryImage)
async def add_gallery_image(image_data: GalleryImageCreate, token: dict = Depends(verify_token)):
    image_obj = GalleryImage(**image_data.model_dump())
    doc = image_obj.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    await db.gallery.insert_one(doc)
    return image_obj

@api_router.delete("/gallery/{image_id}")
async def delete_gallery_image(image_id: str, token: dict = Depends(verify_token)):
    result = await db.gallery.delete_one({"id": image_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Image not found")
    return {"message": "Image deleted successfully"}

# Testimonials
@api_router.get("/testimonials", response_model=List[Testimonial])
async def get_testimonials(approved_only: bool = True):
    query = {"approved": True} if approved_only else {}
    testimonials = await db.testimonials.find(query, {"_id": 0}).sort("created_at", -1).to_list(100)
    for test in testimonials:
        if isinstance(test.get('created_at'), str):
            test['created_at'] = datetime.fromisoformat(test['created_at'])
    return testimonials

@api_router.post("/testimonials", response_model=Testimonial)
async def create_testimonial(testimonial_data: TestimonialCreate):
    testimonial_obj = Testimonial(**testimonial_data.model_dump())
    doc = testimonial_obj.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    await db.testimonials.insert_one(doc)
    return testimonial_obj

@api_router.put("/testimonials/{testimonial_id}/approve")
async def approve_testimonial(testimonial_id: str, token: dict = Depends(verify_token)):
    result = await db.testimonials.update_one(
        {"id": testimonial_id},
        {"$set": {"approved": True}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Testimonial not found")
    return {"message": "Testimonial approved"}

@api_router.delete("/testimonials/{testimonial_id}")
async def delete_testimonial(testimonial_id: str, token: dict = Depends(verify_token)):
    result = await db.testimonials.delete_one({"id": testimonial_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Testimonial not found")
    return {"message": "Testimonial deleted successfully"}

# AI Chat Bot
@api_router.post("/chat", response_model=ChatResponse)
async def chat_with_bot(chat_data: ChatMessage):
    try:
        llm_key = os.environ.get('EMERGENT_LLM_KEY')
        
        # System message with clan context
        system_message = """Ты - PortugalBot, официальный AI-помощник легендарного клана PORTUGAL в игре Steel and Flesh 2.

Информация о клане:
- Название: PORTUGAL CLAN
- Статус: Один из самых влиятельных кланов в Steel and Flesh 2
- Философия: Сила в единстве, честь в победе, легенда в наших битвах

Лидеры клана:
1. Вергилий - Основатель и мудрый лидер, символ чести клана
2. Астер - Главнокомандующий клана, стратег и герой Португалии
3. Денис - Герцог Браги, элитный воин, правая рука Астера

Военная статистика:
- Против Монголии и Казахов: 11 побед, 1 поражение
- Против Франции: 6 побед, 0 поражений
- Против Рима: 4 победы, 4 поражения
- Против ДжК: 1 победа, 5 поражений
- Против Англии: 0 побед, 1 поражение
- Против ОУ: 2 победы, 0 поражений
- Общий счёт: 26 побед / 11 поражений

Как вступить в клан:
- Свяжись с лидером Вергилием в Telegram: @Xroeyrs

Отвечай на вопросы о клане дружелюбно, по-королевски и с гордостью. Всегда на русском языке."""
        
        chat = LlmChat(
            api_key=llm_key,
            session_id=chat_data.session_id,
            system_message=system_message
        ).with_model("openai", "gpt-4o-mini")
        
        user_message = UserMessage(text=chat_data.message)
        response = await chat.send_message(user_message)
        
        return ChatResponse(
            response=response,
            session_id=chat_data.session_id
        )
    except Exception as e:
        logging.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")

# Admin Stats
@api_router.get("/admin/stats")
async def get_admin_stats(token: dict = Depends(verify_token)):
    total_testimonials = await db.testimonials.count_documents({})
    pending_testimonials = await db.testimonials.count_documents({"approved": False})
    approved_testimonials = await db.testimonials.count_documents({"approved": True})
    total_wars = await db.wars.count_documents({})
    total_gallery = await db.gallery.count_documents({})
    
    return {
        "total_testimonials": total_testimonials,
        "pending_testimonials": pending_testimonials,
        "approved_testimonials": approved_testimonials,
        "total_wars": total_wars,
        "total_gallery": total_gallery
    }

# Initialize default data
@api_router.post("/initialize")
async def initialize_data():
    # Check if already initialized
    existing_leaders = await db.leaders.count_documents({})
    if existing_leaders > 0:
        return {"message": "Database already initialized"}
    
    # Leaders data
    leaders = [
        {
            "id": str(uuid.uuid4()),
            "name": "Вергилий",
            "title": "Основатель клана",
            "description": "Мудрый лидер и символ чести клана PORTUGAL. Основал легенду.",
            "image_url": "https://customer-assets.emergentagent.com/job_e7a85aa0-8f83-447e-897d-d6a37e1483e7/artifacts/nrlemlvl_image.png",
            "order": 1
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Астер",
            "title": "Главнокомандующий клана",
            "description": "Стратег и герой Португалии. Ведёт клан к великим победам.",
            "image_url": "https://customer-assets.emergentagent.com/job_e7a85aa0-8f83-447e-897d-d6a37e1483e7/artifacts/bnfzign7_image.png",
            "order": 2
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Денис",
            "title": "Герцог Браги",
            "description": "Элитный воин и правая рука Астера. Непобедим в бою.",
            "image_url": "https://customer-assets.emergentagent.com/job_e7a85aa0-8f83-447e-897d-d6a37e1483e7/artifacts/4im444p4_image.png",
            "order": 3
        }
    ]
    await db.leaders.insert_many(leaders)
    
    # War statistics
    wars = [
        {"id": str(uuid.uuid4()), "opponent": "Монголия и Казахи", "wins": 11, "losses": 1, "order": 1},
        {"id": str(uuid.uuid4()), "opponent": "Франция", "wins": 6, "losses": 0, "order": 2},
        {"id": str(uuid.uuid4()), "opponent": "Рим", "wins": 4, "losses": 4, "order": 3},
        {"id": str(uuid.uuid4()), "opponent": "ДжК", "wins": 1, "losses": 5, "order": 4},
        {"id": str(uuid.uuid4()), "opponent": "Англия", "wins": 0, "losses": 1, "order": 5},
        {"id": str(uuid.uuid4()), "opponent": "ОУ", "wins": 2, "losses": 0, "order": 6}
    ]
    await db.wars.insert_many(wars)
    
    # Gallery - initial 4 images
    gallery = [
        {"id": str(uuid.uuid4()), "image_url": "https://customer-assets.emergentagent.com/job_e7a85aa0-8f83-447e-897d-d6a37e1483e7/artifacts/nrlemlvl_image.png", "created_at": datetime.now(timezone.utc).isoformat()},
        {"id": str(uuid.uuid4()), "image_url": "https://customer-assets.emergentagent.com/job_e7a85aa0-8f83-447e-897d-d6a37e1483e7/artifacts/bnfzign7_image.png", "created_at": datetime.now(timezone.utc).isoformat()},
        {"id": str(uuid.uuid4()), "image_url": "https://customer-assets.emergentagent.com/job_e7a85aa0-8f83-447e-897d-d6a37e1483e7/artifacts/4im444p4_image.png", "created_at": datetime.now(timezone.utc).isoformat()},
        {"id": str(uuid.uuid4()), "image_url": "https://customer-assets.emergentagent.com/job_e7a85aa0-8f83-447e-897d-d6a37e1483e7/artifacts/rsdp2wa0_image.png", "created_at": datetime.now(timezone.utc).isoformat()}
    ]
    await db.gallery.insert_many(gallery)
    
    return {"message": "Database initialized successfully"}

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
    from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Hello World"}
