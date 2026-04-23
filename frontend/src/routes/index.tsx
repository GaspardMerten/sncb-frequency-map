import { createRoute } from "@tanstack/react-router";
import { Link } from "@tanstack/react-router";
import { rootRoute } from "./__root";
import { Layout } from "@/components/Layout";
import { Badge } from "@/components/ui/badge";
import { PAGES } from "@/lib/constants";
import { Train, ArrowRight, Database, Cpu, Eye, FileText, ListOrdered } from "lucide-react";

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

      {/* Report banners */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5 mb-5">
        <Link
          to="/report/missed"
          className="group block rounded-2xl border border-primary/20 bg-gradient-to-r from-rose-500/[0.06] via-amber-500/[0.04] to-primary/[0.06] p-5 transition-all duration-300 hover:shadow-lg hover:shadow-primary/[0.08] hover:-translate-y-0.5"
        >
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-rose-500/15 to-amber-500/10 flex items-center justify-center shrink-0 transition-transform duration-300 group-hover:scale-110">
              <FileText className="w-6 h-6 text-destructive/70" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <h3 className="font-bold text-foreground tracking-tight group-hover:text-primary transition-colors">
                  Missed Connections Report
                </h3>
                <Badge className="bg-rose-50 text-rose-600 border-rose-100 text-[9px] font-semibold">Story</Badge>
              </div>
              <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
                Scrollable data story exploring how delays break thousands of planned transfers across Belgium's rail network.
              </p>
            </div>
            <ArrowRight className="w-4 h-4 text-muted-foreground/30 group-hover:text-primary/60 transition-all duration-300 group-hover:translate-x-1 shrink-0" />
          </div>
        </Link>

        <Link
          to="/rankings"
          className="group block rounded-2xl border border-primary/20 bg-gradient-to-r from-emerald-500/[0.06] via-teal-500/[0.04] to-primary/[0.06] p-5 transition-all duration-300 hover:shadow-lg hover:shadow-primary/[0.08] hover:-translate-y-0.5"
        >
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-emerald-500/15 to-teal-500/10 flex items-center justify-center shrink-0 transition-transform duration-300 group-hover:scale-110">
              <ListOrdered className="w-6 h-6 text-primary/70" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <h3 className="font-bold text-foreground tracking-tight group-hover:text-primary transition-colors">
                  Station Rankings Report
                </h3>
                <Badge className="bg-emerald-50 text-emerald-600 border-emerald-100 text-[9px] font-semibold">Report</Badge>
              </div>
              <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
                Multi-metric ranking of Belgian stations: reach, trains per day, last departure, and commercial speed — colour-coded by region.
              </p>
            </div>
            <ArrowRight className="w-4 h-4 text-muted-foreground/30 group-hover:text-primary/60 transition-all duration-300 group-hover:translate-x-1 shrink-0" />
          </div>
        </Link>
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
