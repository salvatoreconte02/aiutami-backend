import "./card.css";

export default function Card({ children, onClick, hover = true }) {
  return (
    <div className={`card-ui ${hover ? "card-ui--hover" : ""}`} onClick={onClick}>
      {children}
    </div>
  );
}
