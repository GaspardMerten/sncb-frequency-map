import { useState } from "react";
import { Link, useMatches } from "@tanstack/react-router";
import { Menu, PanelLeftClose, PanelLeft, Train } from "lucide-react";
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

  return (
    <>
      {/* Top bar */}
      <header className="fixed top-0 left-0 right-0 z-50 h-12 bg-card/95 backdrop-blur-md border-b border-border flex items-center px-4 gap-3">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="text-primary h-8 w-8"
        >
          {sidebarOpen ? <PanelLeftClose className="w-4 h-4" /> : <PanelLeft className="w-4 h-4" />}
        </Button>

        <Link to="/" className="flex items-center gap-2 text-primary font-semibold text-sm tracking-wide hover:text-primary/80 transition-colors">
          <Train className="w-4 h-4" />
          MobilityTwin
        </Link>

        <nav className="hidden lg:flex items-center gap-0.5 ml-6 text-xs">
          {PAGES.map((page) => {
            const href = `/${page.slug}` as "/" | `/${string}`;
            return (
              <Link
                key={page.slug}
                to={href as "/"}
                className={cn(
                  "px-2.5 py-1.5 rounded-md transition-colors",
                  currentPath === href
                    ? "bg-primary/10 text-primary font-medium"
                    : "text-muted-foreground hover:text-foreground hover:bg-accent",
                )}
              >
                {page.title.split(" ")[0]}
              </Link>
            );
          })}
        </nav>

        {/* Mobile nav */}
        <div className="lg:hidden ml-auto relative">
          <Button variant="ghost" size="icon" onClick={() => setMobileNavOpen(!mobileNavOpen)} className="h-8 w-8">
            <Menu className="w-4 h-4" />
          </Button>
          {mobileNavOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setMobileNavOpen(false)} />
              <div className="absolute right-0 top-10 bg-card rounded-xl shadow-lg border border-border py-2 min-w-[200px] z-50">
                {PAGES.map((page) => {
                  const href = `/${page.slug}` as "/";
                  return (
                    <Link
                      key={page.slug}
                      to={href}
                      onClick={() => setMobileNavOpen(false)}
                      className={cn(
                        "flex items-center gap-2.5 px-4 py-2 text-xs transition-colors",
                        currentPath === `/${page.slug}`
                          ? "bg-primary/10 text-primary"
                          : "text-muted-foreground hover:bg-accent",
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
        </div>
      </header>

      <div className="flex pt-12 h-full">
        {/* Sidebar */}
        {sidebarOpen && sidebar && (
          <aside className="fixed top-12 left-0 bottom-0 w-72 bg-gradient-to-b from-muted/60 to-muted border-r border-border overflow-y-auto z-40 animate-in slide-in-from-left-2 duration-200">
            <div className="p-4 space-y-4">{sidebar}</div>
            <div className="p-4 border-t border-border text-center text-xs text-muted-foreground">
              Powered by <strong className="text-foreground/60">MobilityTwin.Brussels</strong> (ULB)
            </div>
          </aside>
        )}

        {/* Main content */}
        <main
          className={cn(
            "flex-1 overflow-auto transition-[margin] duration-200 ease-out",
            sidebarOpen && sidebar ? "ml-72" : "ml-0",
          )}
        >
          <div className="p-4 lg:p-6 max-w-[1600px]">{children}</div>
        </main>
      </div>
    </>
  );
}
