import { fixupPluginRules } from "@eslint/compat";
import nextConfig from "@dock108/eslint-config";

const addEslint10GlobalsSupport = (scopeManager) => {
  if (!scopeManager || typeof scopeManager.addGlobals === "function") {
    return;
  }

  scopeManager.addGlobals = (names) => {
    const globalScope = scopeManager.globalScope ?? scopeManager.scopes?.[0];

    if (!globalScope || typeof globalScope.__defineGeneric !== "function") {
      return;
    }

    for (const name of names) {
      globalScope.__defineGeneric(name, globalScope.set, globalScope.variables, null, null);
    }

    const namesSet = new Set(names);

    globalScope.through = globalScope.through.filter((reference) => {
      const name = reference.identifier.name;

      if (!namesSet.has(name)) {
        return true;
      }

      const variable = globalScope.set.get(name);
      reference.resolved = variable;
      variable.references.push(reference);
      return false;
    });

    if (globalScope.implicit) {
      globalScope.implicit.variables = globalScope.implicit.variables.filter((variable) => {
        if (!namesSet.has(variable.name)) {
          return true;
        }

        globalScope.implicit.set.delete(variable.name);
        return false;
      });
      globalScope.implicit.left = globalScope.implicit.left.filter(
        (reference) => !namesSet.has(reference.identifier.name),
      );
    }
  };
};

const withEslint10ParserSupport = (parser) => ({
  ...parser,
  parseForESLint(code, options) {
    const result = parser.parseForESLint(code, options);
    addEslint10GlobalsSupport(result.scopeManager);
    return result;
  },
});

const legacyPluginNames = new Set(["import", "jsx-a11y", "react"]);

const withEslint10PluginSupport = (plugins) => Object.fromEntries(
  Object.entries(plugins).map(([name, plugin]) => [
    name,
    legacyPluginNames.has(name) ? fixupPluginRules(plugin) : plugin,
  ]),
);

const configNext = nextConfig.map((entry) => {
  const parser = entry.languageOptions?.parser;

  const nextEntry = parser?.meta?.name === "eslint-config-next/parser"
    ? {
        ...entry,
        languageOptions: {
          ...entry.languageOptions,
          parser: withEslint10ParserSupport(parser),
        },
      }
    : entry;

  if (!nextEntry.plugins) {
    return nextEntry;
  }

  return {
    ...nextEntry,
    plugins: withEslint10PluginSupport(nextEntry.plugins),
  };
});

const config = [
  {
    ignores: ["coverage/**", ".next/**", "out/**", "node_modules/**"],
  },
  ...configNext,
  {
    rules: {
      "react-hooks/set-state-in-effect": "off",
    },
  },
];

export default config;
