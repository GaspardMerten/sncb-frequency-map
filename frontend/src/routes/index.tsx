import { createRoute } from "@tanstack/react-router";
import { Link } from "@tanstack/react-router";
import { rootRoute } from "./__root";
import { Layout } from "@/components/Layout";
import { Badge } from "@/components/ui/badge";
import { PAGES } from "@/lib/constants";
import { Train, ArrowRight, Database, Cpu, Eye } from "lucide-react";

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: HomePage,
});

const PIPELINE = [
  { icon: Database, label: "Fetch GTFS snapshots", sub: "Daily data ingestion" },
  { icon: Cpu, label: "Match & compute", sub: "Segment matching + frequencies" },
  { icon: Eye, label: "Visualize", sub: "Interactive exploration" },
];

function HomePage() {
  return (
    <Layout
      sidebar={
        <>
          <div className="text-center py-6">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-primary to-brand-700 flex items-center justify-center mx-auto mb-3 shadow-lg shadow-primary/20">
              <Train className="w-7 h-7 text-white" />
            </div>
            <h2 className="font-bold text-base text-foreground tracking-tight">SNCB Explorer</h2>
            <p className="text-[11px] text-muted-foreground mt-0.5">Belgian rail & transit analytics</p>
          </div>

          <div className="space-y-1.5">
            <p className="text-[10px] font-semibold text-foreground/40 uppercase tracking-widest mb-2">Data Sources</p>
            <div className="flex flex-wrap gap-1.5">
              <Badge className="bg-blue-50 text-blue-600 border-blue-100 font-medium text-[10px]">GTFS</Badge>
              <Badge className="bg-amber-50 text-amber-600 border-amber-100 font-medium text-[10px]">Infrabel</Badge>
              <Badge className="bg-emerald-50 text-emerald-600 border-emerald-100 font-medium text-[10px]">MobilityTwin</Badge>
            </div>
          </div>

          <div className="border-t border-border/40 pt-3 mt-3">
            <p className="text-[10px] font-semibold text-foreground/40 uppercase tracking-widest mb-3">Pipeline</p>
            <div className="space-y-3">
              {PIPELINE.map((step, i) => (
                <div key={i} className="flex items-start gap-2.5">
                  <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-primary/15 to-primary/5 flex items-center justify-center shrink-0 mt-0.5">
                    <step.icon className="w-3.5 h-3.5 text-primary" />
                  </div>
                  <div>
                    <p className="text-xs font-medium text-foreground/80 leading-tight">{step.label}</p>
                    <p className="text-[10px] text-muted-foreground/60 leading-tight">{step.sub}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      }
    >
      {/* Hero */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-foreground tracking-tight">
          Belgian Rail & Transit <span className="text-gradient">Analytics</span>
        </h1>
        <p className="text-sm text-muted-foreground mt-2 max-w-xl leading-relaxed">
          Explore train frequencies, station reachability, travel times, and punctuality across Belgium's entire transit network.
        </p>
      </div>

      {/* Page cards grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3.5">
        {PAGES.map((page) => (
          <Link
            key={page.slug}
            to={`/${page.slug}` as "/"}
            className="group block rounded-2xl border border-border/50 bg-card p-5 transition-all duration-300 hover:shadow-lg hover:shadow-primary/[0.06] hover:border-primary/20 hover:-translate-y-0.5"
          >
            <div className="flex items-start gap-3.5">
              <div className={`w-11 h-11 rounded-xl bg-gradient-to-br ${page.gradient} flex items-center justify-center shrink-0 transition-transform duration-300 group-hover:scale-110`}>
                <page.icon className="w-5 h-5 text-foreground/70" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-foreground tracking-tight group-hover:text-primary transition-colors duration-200">{page.title}</h3>
                  <ArrowRight className="w-3.5 h-3.5 text-muted-foreground/30 group-hover:text-primary/60 transition-all duration-300 group-hover:translate-x-0.5" />
                </div>
                <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">{page.desc}</p>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </Layout>
  );
}
