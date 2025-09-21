from sqlalchemy import Column, Integer, String, ForeignKey, Float
from sqlalchemy.orm import relationship, declarative_base
from werkzeug.security import generate_password_hash, check_password_hash

Base = declarative_base()

class User(Base):
    __tablename__ = "user"

    id = Column(Integer, primary_key=True)
    login = Column(String(80), unique=True, nullable=False)
    password_hash = Column(String(200), nullable=False)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Case(Base):
    __tablename__ = "case"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    teams = relationship("Team", back_populates="case")


class Team(Base):
    __tablename__ = "team"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    case_id = Column(Integer, ForeignKey("case.id"), nullable=True)

    case = relationship("Case", back_populates="teams")
    evaluations = relationship("FinalEvaluation", back_populates="team")


class FinalEvaluation(Base):
    __tablename__ = "final_evaluation"

    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("case.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("team.id"), nullable=False)
    evaluator_id = Column(Integer, ForeignKey("user.id"), nullable=False)

    product_value = Column(Float, nullable=False)
    scalability = Column(Float, nullable=False)
    ux = Column(Float, nullable=False)
    presentation = Column(Float, nullable=False)

    evaluator = relationship("User", backref="final_evaluation")
    case = relationship("Case", backref="final_evaluation")
    team = relationship("Team", back_populates="evaluations")
