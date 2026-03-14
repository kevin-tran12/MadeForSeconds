export function AboutPage() {
  return (
    <article className="mx-auto max-w-3xl px-4 py-12 md:py-20">
      <h1 className="font-display text-3xl font-bold text-gray-900 md:text-4xl lg:text-5xl">
        About MadeForSeconds
      </h1>
      <div className="mt-8 space-y-6 text-lg leading-relaxed text-gray-700">
        <p>
          Welcome to <span className="font-semibold text-primary-600">MadeForSeconds</span>, a personal collection of recipes that have earned a permanent spot in my kitchen.
        </p>
        <p>
          This app was built with a simple goal: to create a minimal, lightning-fast, and beautiful way to store and share the dishes I make again and again. No life stories, no clutter—just recipes that work.
        </p>
        <p>
          The name comes from that feeling when a dish is so good you immediately go back for a second helping. I hope you find something here that makes you do the same.
        </p>
        <div className="pt-6">
          <h2 className="font-display text-xl font-bold text-gray-900">The Stack</h2>
          <p className="mt-2 text-base text-gray-600">
            This project is also a technical showcase, built to run entirely on Google Cloud's free tier using React, FastAPI, Firestore, and Cloud Run.
          </p>
        </div>
      </div>
    </article>
  )
}
