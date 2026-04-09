import { createRoute } from "@tanstack/react-router";
import { Link } from "@tanstack/react-router";
import { rootRoute } from "./__root";
import { Layout } from "@/components/Layout";
import { Badge } from "@/components/ui/badge";
import { PAGES } from "@/lib/constants";
import { Train } from "lucide-react";

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: HomePage,
});

function HomePage() {
  return (
    <Layout
      sidebar={
        <>
          <div className="text-center py-8">
            <div className="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center mx-auto mb-3">
              <Train className="w-7 h-7 text-primary" />
            </div>
            <h2 className="text-primary font-bold text-lg">SNCB Frequency Explorer</h2>
            <p className="text-xs text-muted-foreground mt-1">Belgian rail & transit analytics</p>
          </div>

          <div className="space-y-1">
            <p className="text-[11px] font-semibold text-primary uppercase tracking-wider mb-2">Data Sources</p>
            <div className="flex flex-wrap gap-1.5">
              <Badge className="bg-blue-100 text-blue-700 border-blue-200">GTFS</Badge>
              <Badge className="bg-amber-100 text-amber-700 border-amber-200">Infrabel</Badge>
              <Badge className="bg-emerald-100 text-emerald-700 border-emerald-200">MobilityTwin</Badge>
            </div>
          </div>

          <div className="space-y-1 pt-2">
            <p className="text-[11px] font-semibold text-primary uppercase tracking-wider mb-2">Pipeline</p>
            <div className="space-y-1.5 text-[11px] text-muted-foreground">
              {["Fetch GTFS snapshots", "Match to Infrabel segments", "Compute frequencies & timetables", "BFS reachability analysis", "Interactive visualization"].map((step, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="w-5 h-5 rounded-full bg-primary text-primary-foreground flex items-center justify-center text-[9px] font-bold shrink-0">{i + 1}</span>
                  {step}
                </div>
              ))}
            </div>
          </div>
        </>
      }
    >
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground">Belgian Rail & Transit Analytics</h1>
        <p className="text-sm text-muted-foreground mt-1">Explore train frequencies, station reachability, travel times, and punctuality across Belgium.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {PAGES.map((page) => (
          <Link
            key={page.slug}
            to={`/${page.slug}` as "/"}
            className="group block bg-card rounded-xl border border-border p-5 hover:border-primary/30 hover:shadow-md transition-all duration-200"
          >
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary group-hover:bg-primary/15 transition-colors shrink-0">
                <page.icon className="w-5 h-5" />
              </div>
              <div>
                <h3 className="font-semibold text-foreground group-hover:text-primary transition-colors">{page.title}</h3>
                <p className="text-xs text-muted-foreground mt-0.5">{page.desc}</p>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </Layout>
  );
}
