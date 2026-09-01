import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const eslintConfig = [
  {
    ignores: ["dist/**", "public/sw.js", "public/ffmpeg-core/**", "container-backend/**"],
  },
  ...nextCoreWebVitals,
  ...nextTypescript,
  {
    rules: {
      "@typescript-eslint/ban-ts-comment": "off",
      "@typescript-eslint/no-unused-vars": "off",
    },
  },
  {
    // This component intentionally resets collection controls when the parsed
    // media item changes. The reset is prop-driven UI state, not an external
    // synchronization loop, so keep the exception narrowly scoped here.
    files: ["src/components/downloader/LocalEngineDownloadCard.tsx"],
    rules: {
      "react-hooks/set-state-in-effect": "off",
    },
  },
];

export default eslintConfig;
