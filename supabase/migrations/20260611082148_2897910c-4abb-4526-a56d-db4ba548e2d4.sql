
-- Add write-side RLS policies for sierra_conversations and sierra_messages
CREATE POLICY "Owner inserts own sierra conversations" ON public.sierra_conversations
  FOR INSERT TO authenticated WITH CHECK (auth.uid() = owner_user_id);
CREATE POLICY "Owner updates own sierra conversations" ON public.sierra_conversations
  FOR UPDATE TO authenticated USING (auth.uid() = owner_user_id) WITH CHECK (auth.uid() = owner_user_id);
CREATE POLICY "Owner deletes own sierra conversations" ON public.sierra_conversations
  FOR DELETE TO authenticated USING (auth.uid() = owner_user_id);

CREATE POLICY "Owner inserts own sierra messages" ON public.sierra_messages
  FOR INSERT TO authenticated WITH CHECK (
    EXISTS (SELECT 1 FROM public.sierra_conversations c
            WHERE c.id = sierra_messages.conversation_id AND c.owner_user_id = auth.uid())
  );
CREATE POLICY "Owner updates own sierra messages" ON public.sierra_messages
  FOR UPDATE TO authenticated USING (
    EXISTS (SELECT 1 FROM public.sierra_conversations c
            WHERE c.id = sierra_messages.conversation_id AND c.owner_user_id = auth.uid())
  ) WITH CHECK (
    EXISTS (SELECT 1 FROM public.sierra_conversations c
            WHERE c.id = sierra_messages.conversation_id AND c.owner_user_id = auth.uid())
  );
CREATE POLICY "Owner deletes own sierra messages" ON public.sierra_messages
  FOR DELETE TO authenticated USING (
    EXISTS (SELECT 1 FROM public.sierra_conversations c
            WHERE c.id = sierra_messages.conversation_id AND c.owner_user_id = auth.uid())
  );
