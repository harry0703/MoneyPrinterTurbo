# Creative experiments and observed outcomes

The WebUI's **Creative experiment** section creates three scripts from one
structured brief: a question, a counterintuitive opening, and an immediate
demonstration. Review the scripts and three-beat plans, choose one,
then use the normal **Generate Video** button. To test another variant, choose
it and generate another task. Each task gets its own UUID in Task Manager.

The resulting task's `script.json` retains the brief, all three proposed
scripts, the selected variant ID, the script model when known, and
`cost_usd: null` when no reliable price is available. The existing task
artifact also records downloaded material sources and selected local clips
when those are available. It does not store credentials or claim a model
predicted audience response. If you edit the chosen script or subject, the
experiment association is deliberately removed for that generation.

After publishing, export aggregate metrics from your analytics tool and
create a UTF-8 CSV with this exact header:

```csv
task_id,impressions,views,three_second_views,completed_views
123e4567-e89b-42d3-a456-426614174000,1000,500,300,125
```

Import it in **Creative outcomes**. You can combine multiple task UUIDs from
the same experiment. The importer accepts at most 500 rows and 1 MiB, rejects
viewer-level columns, and checks that completed views ≤ three-second views ≤
views ≤ impressions. Imported aggregate counts are saved in each task's
`script.json` as `observed_outcome`; the uploaded CSV itself is not saved.

The comparison displays observed 3-second hold and completion rates using
`views` as the denominator. It suggests a hook direction only after at least
two variants each have 100 views. This is a practical minimum, **not** a
statistical significance test. The suggestion is an observational association:
audience mix, publish time, distribution, and other differences may explain
it. Test the suggested direction against a control in the next batch before
claiming improvement. No audience outcome is labeled an AI prediction.
