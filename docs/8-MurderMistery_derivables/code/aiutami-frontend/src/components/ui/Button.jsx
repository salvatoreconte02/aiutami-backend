import "./button.css";

export default function Button({
  children,
  variant = "primary",
  fullWidth = false,
  ...props
}) {
  return (
    <button
      className={`btn btn--${variant} ${fullWidth ? "btn--full" : ""}`}
      {...props}
    >
      {children}
    </button>
  );
}
