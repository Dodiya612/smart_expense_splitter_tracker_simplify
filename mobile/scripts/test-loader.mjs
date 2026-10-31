import { pathToFileURL, fileURLToPath } from 'node:url';
import { resolve as pathResolve, dirname } from 'node:path';
import { existsSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const projectRoot = process.cwd();
const TYPESCRIPT_EXTENSIONS = /\.(ts|tsx)$/;

export async function resolve(specifier, context, nextResolve) {
  let target = specifier;

  if (target.startsWith('@/')) {
    target = pathResolve(projectRoot, 'src', target.slice(2));
  } else if (context.parentURL && (target.startsWith('./') || target.startsWith('../'))) {
    const parentDir = dirname(fileURLToPath(context.parentURL));
    target = pathResolve(parentDir, target);
  }

  // If target doesn't have an extension or is a path without extension
  if (
    !target.includes('node_modules') &&
    !target.endsWith('.ts') &&
    !target.endsWith('.tsx') &&
    !target.endsWith('.mjs') &&
    !target.endsWith('.js') &&
    !target.endsWith('.json')
  ) {
    for (const ext of ['.ts', '.tsx', '.mjs', '.js', '/index.ts', '/index.js']) {
      const candidate = target + ext;
      if (existsSync(candidate)) {
        return {
          url: pathToFileURL(candidate).href,
          shortCircuit: true,
        };
      }
    }
  }

  if (target.startsWith('/') || (process.platform === 'win32' && /^[a-zA-Z]:/.test(target))) {
    if (existsSync(target)) {
      return {
        url: pathToFileURL(target).href,
        shortCircuit: true,
      };
    }
  }

  return nextResolve(specifier, context);
}

export async function load(url, context, defaultLoad) {
  if (TYPESCRIPT_EXTENSIONS.test(url)) {
    const filename = fileURLToPath(url);
    const source = await readFile(filename, 'utf8');
    const { outputText } = ts.transpileModule(source, {
      fileName: filename,
      compilerOptions: {
        module: ts.ModuleKind.ESNext,
        moduleResolution: ts.ModuleResolutionKind.NodeNext,
        target: ts.ScriptTarget.ES2020,
        jsx: ts.JsxEmit.ReactJSX,
      },
    });

    return {
      format: 'module',
      shortCircuit: true,
      source: outputText,
    };
  }

  return defaultLoad(url, context, defaultLoad);
}
