from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from control_plane.core.config import settings
from control_plane.core.security import hash_password, verify_password, create_access_token
from control_plane.db.session import get_db
from control_plane.models.user import User
from control_plane.schemas.user import UserCreate, UserRead
from control_plane.schemas.auth import Token, TokenData
from control_plane.schemas.google_auth import GoogleLoginRequest

from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

import secrets

random_pw = secrets.token_urlsafe(32)
hashed = hash_password(random_pw)


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register_user(payload: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=payload.email,
        username=payload.username,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(subject=user.id, expires_delta=access_token_expires)
    return Token(access_token=access_token)


# dependency to get current user
from fastapi import Security
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: str = Security(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        sub = payload.get("sub")
        if sub is None:
            raise credentials_exception
        token_data = TokenData(user_id=int(sub))
    except (JWTError, ValueError):
        raise credentials_exception

    user = db.query(User).filter(User.id == token_data.user_id).first()
    if user is None:
        raise credentials_exception
    return user

@router.post("/google")
def google_login(
    payload: GoogleLoginRequest,
    db: Session = Depends(get_db),
):
    try:
        idinfo = google_id_token.verify_oauth2_token(
            payload.id_token,
            google_requests.Request(),
            settings.GOOGLE_CLIENT_ID,
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    # Recommended checks
    if idinfo.get("iss") not in ["accounts.google.com", "https://accounts.google.com"]:
        raise HTTPException(status_code=401, detail="Invalid token issuer")

    if not idinfo.get("email"):
        raise HTTPException(status_code=400, detail="Google token missing email")

    # Optional but recommended:
    if idinfo.get("email_verified") is False:
        raise HTTPException(status_code=401, detail="Email not verified by Google")

    email = idinfo["email"].lower().strip()
    google_sub = idinfo.get("sub")  # Google's stable user id

    # 1) Find user by email
    user = db.query(User).filter(User.email == email).first()

    # 2) Create user if not exists
    if not user:
        random_pw = secrets.token_urlsafe(32)
        user = User(
            email=email,
            username=email.split("@")[0], 
            hashed_password=hash_password(random_pw),  
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    # 3) Issue your normal JWT for the app (same as password login)
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(subject=user.id, expires_delta=access_token_expires)
    return Token(access_token=access_token)


