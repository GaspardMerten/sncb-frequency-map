import { useState } from "react";
import { Link, useMatches } from "@tanstack/react-router";
import { Menu, PanelLeftClose, PanelLeft, Train, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { PAGES } from "@/lib/constants";
import { Button } from "@/components/ui/button";

interface LayoutProps {
  sidebar?: React.ReactNode;
  children: React.ReactNode;
}

export function Layout({ sidebar, children }: LayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const matches = useMatches();
  const currentPath = matches[matches.length - 1]?.pathname ?? "/";

  const currentPage = PAGES.find((p) => currentPath === `/${p.slug}`);

  return (
    <>
      {/* Header */}
      <header className="fixed top-0 left-0 right-0 z-50 h-13 glass border-b border-white/20 flex items-center px-4 gap-3">
        {sidebar && (
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="text-foreground/60 hover:text-primary h-8 w-8 rounded-lg"
          >
            {sidebarOpen ? <PanelLeftClose className="w-4 h-4" /> : <PanelLeft className="w-4 h-4" />}
          </Button>
        )}

        <Link to="/" className="flex items-center gap-2.5 hover:opacity-80 transition-opacity">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center shadow-sm">
            <Train className="w-3.5 h-3.5 text-white" />
          </div>
          <span className="font-bold text-sm tracking-tight text-foreground">
            Mobility<span className="text-primary">Twin</span>
          </span>
        </Link>

        <nav className="hidden lg:flex items-center gap-0.5 ml-6">
          {PAGES.map((page) => {
            const href = `/${page.slug}` as "/" | `/${string}`;
            const isActive = currentPath === href;
            return (
              <Link
                key={page.slug}
                to={href as "/"}
                className={cn(
                  "px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all duration-200",
                  isActive
                    ? "bg-primary text-primary-foreground shadow-sm shadow-primary/25"
                    : "text-muted-foreground hover:text-foreground hover:bg-black/[0.04]",
                )}
              >
                {page.shortTitle ?? page.title.split(" ")[0]}
              </Link>
            );
          })}
        </nav>

        {/* Mobile nav trigger */}
        <div className="lg:hidden ml-auto">
          <Button variant="ghost" size="icon" onClick={() => setMobileNavOpen(!mobileNavOpen)} className="h-8 w-8 rounded-lg">
            {mobileNavOpen ? <X className="w-4 h-4" /> : <Menu className="w-4 h-4" />}
          </Button>
        </div>
      </header>

      {/* Mobile nav overlay */}
      {mobileNavOpen && (
        <>
          <div className="fixed inset-0 bg-black/20 backdrop-blur-sm z-40 lg:hidden" onClick={() => setMobileNavOpen(false)} />
          <div className="fixed right-3 top-14 glass rounded-2xl shadow-2xl border border-white/30 py-2 min-w-[220px] z-50 lg:hidden animate-slide-up">
            {PAGES.map((page) => {
              const href = `/${page.slug}` as "/";
              const isActive = currentPath === `/${page.slug}`;
              return (
                <Link
                  key={page.slug}
                  to={href}
                  onClick={() => setMobileNavOpen(false)}
                  className={cn(
                    "flex items-center gap-3 px-4 py-2.5 text-xs transition-all",
                    isActive
                      ? "bg-primary/8 text-primary font-medium"
                      : "text-muted-foreground hover:bg-black/[0.03] hover:text-foreground",
                  )}
                >
                  <page.icon className="w-3.5 h-3.5" />
                  {page.title}
                </Link>
              );
            })}
          </div>
        </>
      )}

      <div className="flex pt-13 h-full">
        {/* Sidebar */}
        {sidebarOpen && sidebar && (
          <aside className="fixed top-13 left-0 bottom-0 w-[280px] bg-gradient-to-b from-background via-background to-muted/40 border-r border-border/60 overflow-y-auto z-40 animate-in slide-in-from-left-2 duration-200">
            {currentPage && (
              <div className="px-4 pt-5 pb-3">
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary/15 to-primary/5 flex items-center justify-center">
                    <currentPage.icon className="w-4 h-4 text-primary" />
                  </div>
                  <div>
                    <h2 className="text-sm font-semibold text-foreground leading-tight">{currentPage.title}</h2>
                    <p className="text-[10px] text-muted-foreground leading-tight mt-0.5">{currentPage.desc}</p>
                  </div>
                </div>
              </div>
            )}
            <div className="px-4 pb-4 space-y-3">{sidebar}</div>
            <div className="sticky bottom-0 p-3 border-t border-border/40 bg-gradient-to-t from-background to-transparent">
              <p className="text-center text-[10px] text-muted-foreground/60">
                Powered by <span className="font-medium text-muted-foreground/80">MobilityTwin.Brussels</span>
              </p>
            </div>
          </aside>
        )}

        {/* Main content */}
        <main
          className={cn(
            "flex-1 overflow-auto transition-[margin] duration-300 ease-out",
            sidebarOpen && sidebar ? "ml-[280px]" : "ml-0",
          )}
        >
          <div className="p-5 lg:p-7 max-w-[1600px]">{children}</div>
        </main>
      </div>
    </>
  );
}
