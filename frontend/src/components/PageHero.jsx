export default function PageHero({ title, subtitle, icon = "💙" }) {
  return (
    <section className="hero">
      <h1>
        <span className="hero__icon">{icon}</span> {title}
      </h1>
      <p>{subtitle}</p>
    </section>
  );
}