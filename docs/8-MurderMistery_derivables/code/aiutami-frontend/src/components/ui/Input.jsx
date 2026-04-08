import "./input.css";

export default function Input({ label, ...props }) {
  return (
    <div className="input-wrap">
      {label && <label className="input-label">{label}</label>}
      <input className="input-ui" {...props} />
    </div>
  );
}
